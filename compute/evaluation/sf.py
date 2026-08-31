"""Evaluate an SF configuration on later, held-out weeks.

Each fit uses the trailing window before the week it scores. Scoring uses
realized μ, so these results measure the map itself, not μ forecasting.

``evaluate`` walks the refits once and returns one row per scored week with:

  * ``oos_pooled_r2``   — held-out pooled R² using realized μ
  * ``rank_spearman``   — mean cross-node rank correlation, per hour
  * ``sign_agree``      — sign match, ±$1 deadband, per node-hour
  * ``topdecile_hit``   — worst-decile nodes the map also flags worst
  * ``coverage``        — scored-week mu-mass with a fitted SF column
  * ``sf_stability``    — SF correlation between adjacent, non-overlapping windows
  * ``is_pooled_r2``    — fit-window pooled R² for comparison

With ``rho_min`` the fit's unit becomes the collinear *group* rather than the
individual constraint, and three more columns appear:

  * ``n_groups``          — groups the window's constraints collapsed into
  * ``group_churn``       — how much group membership changes from the prior window
  * ``sf_stability_proj`` — (``--control``) the ungrouped SF expressed as groups

``--persist-eval`` writes ``oos_r2``/``coverage``/``sf_stability`` into
``sf_window_meta``.

Metric helpers are copied here so this module does not depend on ``experiments/``.

    docker compose run --rm compute \
      python -m compute.evaluation.sf --run-id <id> --start 2025-01-01 --end 2026-01-01

"""
from __future__ import annotations

import argparse
import gc
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from scipy.stats import rankdata

from shared.settings import settings
from compute.sf_map.config import (
    REFIT_DAYS as DEFAULT_REFIT_DAYS, WINDOW_DAYS as DEFAULT_WINDOW_DAYS,
)
from compute.sf_map.model.fit import (
    MIN_BINDING_HOURS, RIDGE_LAMBDA, STD_FLOOR, implied_shift_factors,
)
from compute.sf_map.model.grouping import (
    aggregate_mu, constraint_linkage, cut_groups, group_members, project_sf,
)
from compute.inputs.dam import load_congestion_panel, load_shadow_prices
from compute.sf_map.storage.persist import count_null_eval, update_eval_metrics

log = logging.getLogger("compute.evaluation.sf")

BASE_DIR = Path(__file__).parent
RUNS_ROOT = BASE_DIR.parent / "runs"

# Shared defaults for the μ forecast and map runner.
SIGN_DEADBAND = 1.0   # $/MWh — ignore congestion-quiet node-hours


# --------------------------------------------------------------- metric fns
# Kept here to avoid an ``experiments`` dependency.

def r2(y: np.ndarray, y_hat: np.ndarray) -> float:
    m = np.isfinite(y) & np.isfinite(y_hat)
    y, y_hat = y[m], y_hat[m]
    if y.size < 2:
        return float("nan")
    ss_tot = float(((y - y.mean()) ** 2).sum())
    if ss_tot <= 0.0:
        return float("nan")
    return 1.0 - float(((y - y_hat) ** 2).sum()) / ss_tot


def row_spearman(Y: np.ndarray, Y_hat: np.ndarray) -> float:
    out = []
    for a, b in zip(Y, Y_hat):
        m = np.isfinite(a) & np.isfinite(b)
        if m.sum() < 10 or np.ptp(a[m]) == 0 or np.ptp(b[m]) == 0:
            continue
        with np.errstate(invalid="ignore", divide="ignore"):
            out.append(np.corrcoef(rankdata(a[m]), rankdata(b[m]))[0, 1])
    return float(np.mean(out)) if out else float("nan")


def sign_agreement(Y: np.ndarray, Y_hat: np.ndarray) -> float:
    m = np.isfinite(Y) & np.isfinite(Y_hat) & (np.abs(Y) > SIGN_DEADBAND)
    if m.sum() == 0:
        return float("nan")
    return float((np.sign(Y[m]) == np.sign(Y_hat[m])).mean())


def topdecile_hit(Y: np.ndarray, Y_hat: np.ndarray) -> float:
    out = []
    for a, b in zip(Y, Y_hat):
        m = np.isfinite(a) & np.isfinite(b)
        n = int(m.sum())
        if n < 20:
            continue
        k = max(1, n // 10)
        top_true = set(np.argsort(-a[m])[:k])
        top_pred = set(np.argsort(-b[m])[:k])
        out.append(len(top_true & top_pred) / k)
    return float(np.mean(out)) if out else float("nan")


def predict(M_score: pd.DataFrame, SF: pd.DataFrame) -> np.ndarray:
    """C_hat = -M · SFᵀ over the constraints the fit actually kept."""
    cols = M_score.columns.intersection(SF.index)
    return -(M_score[cols].to_numpy(float) @ SF.loc[cols].to_numpy(float))


def _sf_corr(A: pd.DataFrame, B: pd.DataFrame) -> float:
    shared = A.index.intersection(B.index)
    if len(shared) < 5:
        return float("nan")
    with np.errstate(invalid="ignore", divide="ignore"):
        return float(np.corrcoef(A.loc[shared].to_numpy(float).ravel(),
                                 B.loc[shared].to_numpy(float).ravel())[0, 1])


def _membership_churn(prev: pd.Series | None, cur: pd.Series | None) -> float:
    """Average overlap of shared groups' members across two windows.

    Groups are named after their largest member. A score of 1 means every shared
    group has the same members; lower scores mean members were added or removed.
    New or removed groups are reported separately by ``n_groups``.
    """
    if prev is None or cur is None or prev.empty or cur.empty:
        return float("nan")
    a = {g: set(m.index) for g, m in prev.groupby(prev)}
    b = {g: set(m.index) for g, m in cur.groupby(cur)}
    shared = set(a) & set(b)
    if not shared:
        return float("nan")
    return float(np.mean([
        len(a[g] & b[g]) / len(a[g] | b[g]) for g in shared
    ]))


def evaluate(
    M: pd.DataFrame,
    C: pd.DataFrame,
    window_days: int = DEFAULT_WINDOW_DAYS,
    refit_days: int = DEFAULT_REFIT_DAYS,
    lam: float = RIDGE_LAMBDA,
    min_hours: int = MIN_BINDING_HOURS,
    standardize: bool = True,
    std_floor: float = STD_FLOOR,
    rho_min: float | None = None,
    control: bool = False,
    linkage_cache: dict | None = None,
    score_from: pd.Timestamp | None = None,
    refit_origin: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Return one row per scored week. M and C do not need matching indexes.

    ``score_from`` skips earlier scores but retains their required history.
    ``rho_min`` fits groups of closely related constraints and adds group counts.
    ``control`` also calculates the ungrouped comparison; it roughly doubles work.
    Pass ``linkage_cache`` to reuse each window's grouping tree across a sweep.
    """
    idx = M.index.union(C.index).sort_values()
    M, C = M.reindex(idx).fillna(0.0), C.reindex(idx)

    day = pd.Timedelta(days=1)
    win = pd.Timedelta(days=window_days)
    refit = pd.Timedelta(days=refit_days)
    days = pd.Index(M.index.normalize().unique()).sort_values()
    end_day = days[-1]

    def window_labels(Mw: pd.DataFrame, lo, hi) -> pd.Series | None:
        if rho_min is None or Mw.empty:
            return None
        key = (lo, hi)
        if linkage_cache is None:
            return cut_groups(constraint_linkage(Mw), rho_min)
        if key not in linkage_cache:
            linkage_cache[key] = constraint_linkage(Mw)
        return cut_groups(linkage_cache[key], rho_min)

    def fit(lo, hi, mh=min_hours, grouped=True) -> tuple[pd.DataFrame, pd.Series | None]:
        """Returns (SF, labels). ``grouped=False`` forces the ungrouped fit —
        that is the control arm, not a different configuration."""
        w = (M.index >= lo) & (M.index < hi)
        Mw, Cw = M.loc[w], C.loc[w]
        if Mw.empty:
            return pd.DataFrame(), None
        labels = window_labels(Mw, lo, hi) if grouped else None
        M_fit = aggregate_mu(Mw, labels) if labels is not None else Mw
        SF = implied_shift_factors(M_fit, Cw, lam=lam, min_hours=mh,
                                   standardize=standardize, std_floor=std_floor)
        return SF, labels

    def score(lo, hi, sf, labels) -> tuple:
        if sf.empty:
            return (np.nan,) * 4
        Ms = M.loc[(M.index >= lo) & (M.index < hi)]
        Cs = C.loc[(C.index >= lo) & (C.index < hi)]
        i = Ms.index.intersection(Cs.index)
        if not len(i):
            return (np.nan,) * 4
        Ms = Ms.loc[i]
        # Use the fit's groups. New scored-week constraints have no fitted group
        # and are counted as uncovered by ``coverage``.
        if labels is not None:
            Ms = aggregate_mu(Ms, labels)
            if Ms.empty:
                return (np.nan,) * 4
        Y = Cs.loc[i, sf.columns].to_numpy(float)
        Yh = predict(Ms, sf)
        return (r2(Y.ravel(), Yh.ravel()), row_spearman(Y, Yh),
                sign_agreement(Y, Yh), topdecile_hit(Y, Yh))

    # Keep a fixed refit grid when skipped warmup or chunked loading changes the
    # first loaded day.
    origin = (pd.Timestamp(refit_origin) if refit_origin is not None
              else days[0] + win)
    starts = pd.date_range(origin, end_day, freq=refit, inclusive="left")
    if score_from is not None:
        starts = starts[starts >= score_from]
    if not len(starts):
        return pd.DataFrame()
    log.info("evaluate: window=%dd refit=%dd λ=%g min_hours=%d rho_min=%s%s — %d "
             "refit boundaries [%s → %s]", window_days, refit_days, lam, min_hours,
             rho_min, " +control" if control else "",
             len(starts), starts[0].date(), starts[-1].date())
    tick = max(1, len(starts) // 8)   # ~8 progress lines per combo
    rows: list[dict] = []
    prev_labels: pd.Series | None = None
    for k, s in enumerate(starts):
        if k and k % tick == 0:
            log.info("  ...scored %d/%d weeks (through %s)",
                     k, len(starts), s.date())
        score_end = min(s + refit, end_day + day)

        # Fit on the window before the scored week; reuse it for stability.
        SF, labels = fit(s - win, s)
        if SF.empty:
            continue
        oos_r2, spearman, sign, topdec = score(s, score_end, SF, labels)

        # Comparison fit whose window includes the scored week.
        SF_pipe, lab_pipe = fit(score_end - win, score_end)
        is_r2, *_ = score(score_end - win, score_end, SF_pipe, lab_pipe)

        # Compare two adjacent, non-overlapping fit windows. Early weeks lack
        # enough history and return NaN.
        SF_older, lab_older = fit(s - 2 * win, s - win)
        stability = (_sf_corr(SF_older, SF) if not SF_older.empty
                     else float("nan"))

        # Optional ungrouped comparison, expressed using each window's groups.
        stability_proj = float("nan")
        if control and rho_min is not None and labels is not None:
            SF_u, _ = fit(s - win, s, grouped=False)
            SF_u_older, _ = fit(s - 2 * win, s - win, grouped=False)
            if not SF_u.empty and not SF_u_older.empty and lab_older is not None:
                M_win = M.loc[(M.index >= s - win) & (M.index < s)]
                M_old = M.loc[(M.index >= s - 2 * win) & (M.index < s - win)]
                proj_new = project_sf(SF_u, group_members(M_win, labels))
                proj_old = project_sf(SF_u_older, group_members(M_old, lab_older))
                stability_proj = _sf_corr(proj_old, proj_new)

        # Share of scored-week μ mass represented by fitted columns.
        M_score = M.loc[(M.index >= s) & (M.index < score_end)]
        if labels is not None:
            kept = {c for c, g in labels.items() if g in set(SF.index)}
            cov_cols = M_score.columns.intersection(pd.Index(sorted(kept)))
        else:
            cov_cols = M_score.columns.intersection(SF.index)
        mass_all = float(M_score.abs().to_numpy(float).sum())
        mass_in = float(M_score[cov_cols].abs().to_numpy(float).sum())
        coverage = mass_in / mass_all if mass_all > 0 else np.nan

        # Count active constraints, their groups, and the rows kept after the
        # minimum-binding-hours filter.
        M_win = M.loc[(M.index >= s - win) & (M.index < s)]
        active = M_win.columns[(M_win != 0).any()]
        rows.append({
            "score_start": s,
            "score_end": score_end,
            "window_start": s - win,
            "n_kept": int(SF.shape[0]),
            "n_constraints": int(active.size),
            "n_groups": int(labels.loc[active].nunique()) if labels is not None
                        else np.nan,
            "oos_pooled_r2": oos_r2,
            "is_pooled_r2": is_r2,
            "rank_spearman": spearman,
            "sign_agree": sign,
            "topdecile_hit": topdec,
            "coverage": coverage,
            "sf_stability": stability,
            "sf_stability_proj": stability_proj,
            "group_churn": _membership_churn(prev_labels, labels),
        })
        prev_labels = labels
    return pd.DataFrame(rows)


def eval_chunks(score_from: pd.Timestamp, end: pd.Timestamp, refit_days: int,
                chunk_weeks: int) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Partition the scored grid into bounded, exclusive-end week chunks."""
    if chunk_weeks < 1:
        raise ValueError("chunk_weeks must be positive")
    end = pd.Timestamp(end).tz_convert(score_from.tz)
    step = pd.Timedelta(days=refit_days)
    starts = pd.date_range(score_from, end, freq=step, inclusive="left")
    return [(block[0], min(block[-1] + step, end))
            for block in (starts[i:i + chunk_weeks]
                          for i in range(0, len(starts), chunk_weeks)) if len(block)]


def evaluate_chunked(
    load_panels,
    *,
    score_from: pd.Timestamp,
    end: pd.Timestamp,
    chunk_weeks: int,
    window_days: int = DEFAULT_WINDOW_DAYS,
    refit_days: int = DEFAULT_REFIT_DAYS,
    **evaluate_kwargs,
) -> pd.DataFrame:
    """Evaluate bounded chunks while retaining the history each score needs."""
    # Keep one leading score so ``--persist-eval`` can update the boundary week.
    first_score = score_from - pd.Timedelta(days=window_days)
    windows = eval_chunks(first_score, end, refit_days, chunk_weeks)
    if not windows:
        return pd.DataFrame()

    win = pd.Timedelta(days=window_days)
    refit = pd.Timedelta(days=refit_days)
    origin = first_score
    parts: list[pd.DataFrame] = []
    for n, (chunk_start, chunk_end) in enumerate(windows, start=1):
        # Later chunks include the prior score to calculate group churn.
        is_first = n == 1
        read_start = chunk_start - 2 * win - (pd.Timedelta(0) if is_first else refit)
        log.info("eval chunk %d/%d: scores [%s, %s), reads [%s, %s)",
                 n, len(windows), chunk_start.date(), chunk_end.date(),
                 read_start.date(), chunk_end.date())
        M, C = load_panels(read_start, chunk_end)
        try:
            if M.empty or C.empty:
                log.warning("eval chunk %d/%d has empty panel(s): M=%s C=%s",
                            n, len(windows), M.shape, C.shape)
                continue
            df = evaluate(
                M, C, window_days=window_days, refit_days=refit_days,
                score_from=chunk_start if is_first else chunk_start - refit,
                refit_origin=origin,
                **evaluate_kwargs,
            )
            df = df[(df["score_start"] >= chunk_start)
                    & (df["score_start"] < chunk_end)]
            if not df.empty:
                parts.append(df)
        finally:
            del M, C
            # The grouping cache is only useful within one chunk.
            cache = evaluate_kwargs.get("linkage_cache")
            if cache is not None:
                cache.clear()
            gc.collect()
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def sf_decay(
    M: pd.DataFrame,
    C: pd.DataFrame,
    window_days: int = DEFAULT_WINDOW_DAYS,
    deltas_days: tuple[int, ...] = (7, 14, 30, 60),
    anchor_step_days: int = 7,
    lam: float = RIDGE_LAMBDA,
    min_hours: int = MIN_BINDING_HOURS,
    standardize: bool = True,
    std_floor: float = STD_FLOOR,
    rho_min: float | None = None,
    linkage_cache: dict | None = None,
) -> pd.DataFrame:
    """Return SF correlation by time lag, with one row per requested lag.

    Fits are reused across lags. Use a lag at least as long as the fit window
    when the two windows must not overlap.
    """
    idx = M.index.union(C.index).sort_values()
    M, C = M.reindex(idx).fillna(0.0), C.reindex(idx)
    win = pd.Timedelta(days=window_days)
    days = pd.Index(M.index.normalize().unique()).sort_values()
    anchors = pd.date_range(days[0] + win, days[-1],
                            freq=pd.Timedelta(days=anchor_step_days), inclusive="left")
    log.info("sf_decay: fitting %d anchors (window=%dd, λ=%g, rho_min=%s) for Δ=%s",
             len(anchors), window_days, lam, rho_min, list(deltas_days))

    SFs: dict[pd.Timestamp, pd.DataFrame] = {}
    for a in anchors:
        w = (M.index >= a - win) & (M.index < a)
        Mw, Cw = M.loc[w], C.loc[w]
        if Mw.empty:
            continue
        M_fit = Mw
        if rho_min is not None:
            key = (a - win, a)
            if linkage_cache is None:
                link = constraint_linkage(Mw)
            else:
                if key not in linkage_cache:
                    linkage_cache[key] = constraint_linkage(Mw)
                link = linkage_cache[key]
            M_fit = aggregate_mu(Mw, cut_groups(link, rho_min))
        sf = implied_shift_factors(M_fit, Cw, lam=lam, min_hours=min_hours,
                                   standardize=standardize, std_floor=std_floor)
        if not sf.empty:
            SFs[a] = sf

    keys = pd.DatetimeIndex(sorted(SFs))
    tol = pd.Timedelta(days=anchor_step_days) / 2
    rows: list[dict] = []
    for D in deltas_days:
        delta = pd.Timedelta(days=D)
        corrs: list[float] = []
        for a in keys:
            # Use the nearest scheduled anchor.
            target = a + delta
            j = keys.get_indexer([target], method="nearest")[0]
            a2 = keys[j]
            if abs(a2 - target) > tol or a2 == a:
                continue
            corrs.append(_sf_corr(SFs[a], SFs[a2]))
        corrs = [c for c in corrs if np.isfinite(c)]
        rows.append({
            "delta_days": D,
            "mean_corr": float(np.mean(corrs)) if corrs else float("nan"),
            "n_pairs": len(corrs),
        })
    return pd.DataFrame(rows)


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run-id", required=True,
                   help="Labels the output CSV under runs/<run_id>/sf/eval.csv.")
    p.add_argument("--start", type=_parse_date, required=True,
                   help="Inclusive first day to score (YYYY-MM-DD).")
    p.add_argument("--end", type=_parse_date, required=True,
                   help="Exclusive last day to score (YYYY-MM-DD).")
    p.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    p.add_argument("--refit-days", type=int, default=DEFAULT_REFIT_DAYS)
    p.add_argument("--ridge-lambda", type=float, default=RIDGE_LAMBDA)
    p.add_argument("--min-binding-hours", type=int, default=MIN_BINDING_HOURS)
    p.add_argument("--std-floor", type=float, default=STD_FLOOR)
    p.add_argument("--no-standardize", dest="standardize", action="store_false")
    p.add_argument("--persist-eval", action="store_true",
                   help="Backfill oos_r2/coverage/sf_stability onto this "
                        "run_id's existing sf_window_meta rows (from an earlier "
                        "runner --persist-sf with matching hyperparameters). "
                        "Matched by score_start.")
    p.add_argument("--emit-decay", action="store_true",
                   help="Also compute the SF drift curve corr(SF_t, SF_{t+Δ}) "
                        "and save decay.csv.")
    p.add_argument("--deltas", type=str, default="7,14,30,60",
                   help="Comma-separated Δ (days) for --emit-decay. Include a Δ "
                        ">= --window-days for a genuinely DISJOINT pair; below "
                        "that the two fits share hours (Δ=60 on a 240d window "
                        "overlaps 75%%) and the curve measures overlap, not drift.")
    p.add_argument("--rho-min", type=float, default=None,
                   help="Collinear-group the mu columns and fit on the group "
                        "aggregate (S2 / plan 0083). Every pair inside a group "
                        "correlates >= this. Omit for the ungrouped fit; 1.0 is "
                        "an explicit no-op.")
    p.add_argument("--control", action="store_true",
                   help="With --rho-min, also emit sf_stability_proj: the "
                        "ungrouped SF projected into the group row-space. The "
                        "apples-to-apples drift baseline for R3. ~2x cost.")
    p.add_argument("--chunk-weeks", type=int, default=32,
                   help="Evaluate this many weekly folds per loaded panel "
                        "(default 32). Each chunk retains the required 2×window "
                        "history for disjoint stability, then releases its dense "
                        "panels. Use 0 for the legacy full-history evaluation.")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    if args.chunk_weeks < 0:
        p.error("--chunk-weeks must be non-negative")

    # Reuse grouping trees across evaluation and decay.
    linkage_cache: dict = {}
    if args.chunk_weeks:
        score_from = pd.Timestamp(args.start, tz="UTC")
        end = pd.Timestamp(args.end, tz="UTC")
        with psycopg.connect(settings.pg_dsn) as conn:
            def load_chunk(read_start, chunk_end):
                return (load_shadow_prices(conn, read_start, chunk_end),
                        load_congestion_panel(conn, read_start, chunk_end))

            df_full = evaluate_chunked(
                load_chunk, score_from=score_from, end=end,
                chunk_weeks=args.chunk_weeks,
                window_days=args.window_days, refit_days=args.refit_days,
                lam=args.ridge_lambda, min_hours=args.min_binding_hours,
                standardize=args.standardize, std_floor=args.std_floor,
                rho_min=args.rho_min, control=args.control,
                linkage_cache=linkage_cache,
            )
        panel_tz = score_from.tz
    else:
        # Full-panel option for one-off comparisons.
        read_start = args.start - timedelta(days=2 * args.window_days)
        log.info("loading panels: read=[%s, %s), score=[%s, %s)",
                 read_start, args.end, args.start, args.end)
        with psycopg.connect(settings.pg_dsn) as conn:
            M = load_shadow_prices(conn, read_start, args.end)
            C = load_congestion_panel(conn, read_start, args.end)
        if M.empty or C.empty:
            log.error("empty panel(s): M=%s C=%s", M.shape, C.shape)
            return 3
        log.info("M=%s C=%s", M.shape, C.shape)
        df_full = evaluate(M, C, args.window_days, args.refit_days, args.ridge_lambda,
                           args.min_binding_hours, args.standardize, args.std_floor,
                           rho_min=args.rho_min, control=args.control,
                           linkage_cache=linkage_cache)
        panel_tz = M.index.tz
    # Display requested weeks only; retain the leading row for metadata updates.
    start_ts = pd.Timestamp(args.start, tz=panel_tz)
    df = df_full[df_full["score_start"] >= start_ts].reset_index(drop=True)
    if df.empty:
        log.error("no scored weeks in [%s, %s)", args.start, args.end)
        return 4

    if args.persist_eval:
        def _clean(v: float):
            return None if v is None or not np.isfinite(v) else float(v)
        rows = [
            (r.score_start.to_pydatetime(), _clean(r.oos_pooled_r2),
             _clean(r.coverage), _clean(r.sf_stability))
            for r in df_full.itertuples()
        ]
        with psycopg.connect(settings.pg_dsn) as conn:
            matched = update_eval_metrics(conn, args.run_id, rows)
            conn.commit()
            remaining = count_null_eval(conn, args.run_id)
        log.info("backfilled sf_window_meta: %d rows matched for run_id=%s",
                 matched, args.run_id)
        if remaining:
            log.warning("%d sf_window_meta rows for run_id=%s still have NULL "
                        "oos_r2 (score_start/refit misalignment, or out of the "
                        "eval range)", remaining, args.run_id)

    out_dir = RUNS_ROOT / args.run_id / "sf"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "eval.csv"
    df.to_csv(out_path, index=False)

    pd.set_option("display.width", 220)
    drop = ["score_end", "window_start"]
    if args.rho_min is None:
        drop += ["n_groups", "group_churn", "sf_stability_proj"]
    elif not args.control:
        drop += ["sf_stability_proj"]
    show = df.drop(columns=drop)
    print(show.to_string(index=False, float_format=lambda v: f"{v:8.3f}"))
    print(f"\n=== eval over {len(df)} weeks "
          f"(window {args.window_days}d, refit {args.refit_days}d, "
          f"λ {args.ridge_lambda:g}, min_hours {args.min_binding_hours}, "
          f"rho_min {args.rho_min}) ===")
    print(f"OOS pooled R2   (oracle μ, the ceiling) : {df.oos_pooled_r2.mean():.3f}")
    print(f"in-sample R2    (what the pipeline reports) : {df.is_pooled_r2.mean():.3f}")
    print(f"rank-Spearman   : {df.rank_spearman.mean():.3f}")
    print(f"sign-agree      : {df.sign_agree.mean():.3f}")
    print(f"top-decile hit  : {df.topdecile_hit.mean():.3f}")
    print(f"coverage        : {df.coverage.mean():.3f}")
    print(f"SF stability    (disjoint {args.window_days}d) : "
          f"{df.sf_stability.mean():.3f}")
    if args.rho_min is not None:
        print(f"n_groups        : {df.n_groups.mean():.0f} "
              f"of {df.n_constraints.mean():.0f} window-active constraints "
              f"({df.n_constraints.mean() / max(df.n_groups.mean(), 1):.2f}x), "
              f"{df.n_kept.mean():.0f} kept after min_hours")
        print(f"group churn     (membership Jaccard) : {df.group_churn.mean():.3f}")
        if args.control:
            print(f"SF stability    (CONTROL: ungrouped, projected) : "
                  f"{df.sf_stability_proj.mean():.3f}")
            print(f"  → grouping delta : "
                  f"{df.sf_stability.mean() - df.sf_stability_proj.mean():+.3f}")
    log.info("wrote %s", out_path)

    if args.emit_decay:
        if args.chunk_weeks:
            # Decay needs the full history.
            read_start = args.start - timedelta(days=2 * args.window_days)
            log.info("loading full panel for requested decay: [%s, %s)",
                     read_start, args.end)
            with psycopg.connect(settings.pg_dsn) as conn:
                M = load_shadow_prices(conn, read_start, args.end)
                C = load_congestion_panel(conn, read_start, args.end)
        deltas = tuple(int(x) for x in args.deltas.split(",") if x.strip())
        decay = sf_decay(M, C, args.window_days, deltas_days=deltas,
                         lam=args.ridge_lambda,
                         min_hours=args.min_binding_hours,
                         standardize=args.standardize, std_floor=args.std_floor,
                         rho_min=args.rho_min, linkage_cache=linkage_cache)
        decay.to_csv(out_dir / "decay.csv", index=False)
        print("\n=== SF decay curve — corr(SF_t, SF_{t+Δ}) ===")
        print(decay.to_string(index=False, float_format=lambda v: f"{v:.3f}"))
        log.info("wrote %s", out_dir / "decay.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
