"""Honest out-of-window evaluation of an SF configuration — the production
home of what ``experiments/ibp_out_of_window`` proved as one-offs.

The production fit (``rolling.rolling_bp``) uses ``window_end = score_end``: the
fit window CONTAINS the week it scores, giving an in-sample R2 ~0.986. This
module fits on the trailing window ending STRICTLY BEFORE the scored week
(``window_end = refit_start``) and scores the next ``refit_days`` from realized
mu (oracle). That isolates the SF map from any bind-forecasting skill — it is
the ceiling, ~0.746, not 0.986.

``evaluate`` walks the refits once and returns one row per scored week with:

  * ``oos_pooled_r2``   — honest OOS pooled R2, oracle mu (the ceiling)
  * ``rank_spearman``   — mean cross-node rank correlation, per hour
  * ``sign_agree``      — sign match, ±$1 deadband, per node-hour
  * ``topdecile_hit``   — worst-decile nodes the map also flags worst
  * ``coverage``        — scored-week mu-mass with a fitted SF column
  * ``sf_stability``    — corr over DISJOINT adjacent windows (not the
                          overlap-contaminated 0.90; the honest ~0.47)
  * ``is_pooled_r2``    — the in-sample number, for side-by-side

One reusable pass: ``sweep_ibp`` (S1.4) selects on these, and ``--persist-eval``
(S1.3) writes ``oos_r2``/``coverage`` into ``sf_window_meta``.

The pure metric fns are lifted (not imported) from the frozen harness so this
kept module carries no dependency on ``experiments/``.

    docker compose run --rm compute \
      python -m compute.sf.eval --run-id <id> --start 2025-01-01 --end 2026-01-01
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
from scipy.stats import rankdata

from compute.config import PG_DSN
from compute.sf.fit import (
    MIN_BINDING_HOURS, RIDGE_LAMBDA, STD_FLOOR, implied_shift_factors,
)
from compute.sf.panels import load_congestion_panel, load_shadow_prices

log = logging.getLogger("compute.sf.eval")

BASE_DIR = Path(__file__).parent
RUNS_ROOT = BASE_DIR.parent / "runs"

DEFAULT_WINDOW_DAYS = 60
DEFAULT_REFIT_DAYS = 7
SIGN_DEADBAND = 1.0   # $/MWh — ignore congestion-quiet node-hours


# --------------------------------------------------------------- metric fns
# Lifted verbatim from experiments/ibp_out_of_window (common.py,
# screening_and_coverage.py) so results stay directly comparable.

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


def evaluate(
    M: pd.DataFrame,
    C: pd.DataFrame,
    window_days: int = DEFAULT_WINDOW_DAYS,
    refit_days: int = DEFAULT_REFIT_DAYS,
    lam: float = RIDGE_LAMBDA,
    min_hours: int = MIN_BINDING_HOURS,
    standardize: bool = True,
    std_floor: float = STD_FLOOR,
) -> pd.DataFrame:
    """One row per scored week. M, C need NOT be pre-aligned."""
    idx = M.index.union(C.index).sort_values()
    M, C = M.reindex(idx).fillna(0.0), C.reindex(idx)

    day = pd.Timedelta(days=1)
    win = pd.Timedelta(days=window_days)
    refit = pd.Timedelta(days=refit_days)
    days = pd.Index(M.index.normalize().unique()).sort_values()
    end_day = days[-1]

    def fit(lo, hi, mh=min_hours) -> pd.DataFrame:
        w = (M.index >= lo) & (M.index < hi)
        Mw, Cw = M.loc[w], C.loc[w]
        if Mw.empty:
            return pd.DataFrame()
        return implied_shift_factors(Mw, Cw, lam=lam, min_hours=mh,
                                     standardize=standardize, std_floor=std_floor)

    def score(lo, hi, sf) -> tuple:
        if sf.empty:
            return (np.nan,) * 4
        Ms = M.loc[(M.index >= lo) & (M.index < hi)]
        Cs = C.loc[(C.index >= lo) & (C.index < hi)]
        i = Ms.index.intersection(Cs.index)
        if not len(i):
            return (np.nan,) * 4
        Y = Cs.loc[i, sf.columns].to_numpy(float)
        Yh = predict(Ms.loc[i], sf)
        return (r2(Y.ravel(), Yh.ravel()), row_spearman(Y, Yh),
                sign_agreement(Y, Yh), topdecile_hit(Y, Yh))

    # First refit needs a full trailing window behind it.
    starts = pd.date_range(days[0] + win, end_day, freq=refit, inclusive="left")
    rows: list[dict] = []
    for s in starts:
        score_end = min(s + refit, end_day + day)

        # HONEST fit: window ends where scoring begins. This is also the
        # "newer" window for the disjoint-stability pair — fit once, reuse.
        SF = fit(s - win, s)
        if SF.empty:
            continue
        oos_r2, spearman, sign, topdec = score(s, score_end, SF)

        # IN-SAMPLE fit: window ends where scoring ends (contains the week).
        SF_pipe = fit(score_end - win, score_end)
        is_r2, *_ = score(score_end - win, score_end, SF_pipe)

        # DISJOINT stability: older 60d vs the honest (newer) 60d. NaN until
        # 2×window of history sits behind s.
        SF_older = fit(s - 2 * win, s - win)
        stability = _sf_corr(SF_older, SF) if not SF_older.empty else float("nan")

        # COVERAGE: scored-week mu-mass carried by fitted (kept) constraints.
        M_score = M.loc[(M.index >= s) & (M.index < score_end)]
        cov_cols = M_score.columns.intersection(SF.index)
        mass_all = float(M_score.abs().to_numpy(float).sum())
        mass_in = float(M_score[cov_cols].abs().to_numpy(float).sum())
        coverage = mass_in / mass_all if mass_all > 0 else np.nan

        rows.append({
            "score_start": s,
            "score_end": score_end,
            "window_start": s - win,
            "n_kept": int(SF.shape[0]),
            "oos_pooled_r2": oos_r2,
            "is_pooled_r2": is_r2,
            "rank_spearman": spearman,
            "sign_agree": sign,
            "topdecile_hit": topdec,
            "coverage": coverage,
            "sf_stability": stability,
        })
    return pd.DataFrame(rows)


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run-id", required=True,
                   help="Labels the output CSV under runs/<run_id>/ibp/eval.csv.")
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
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    # Read window extends back 2×window so the earliest refit gets its full
    # trailing history AND its disjoint-stability predecessor.
    read_start = args.start - timedelta(days=2 * args.window_days)
    log.info("loading panels: read=[%s, %s), score=[%s, %s)",
             read_start, args.end, args.start, args.end)
    with psycopg.connect(PG_DSN) as conn:
        M = load_shadow_prices(conn, read_start, args.end)
        C = load_congestion_panel(conn, read_start, args.end)
    if M.empty or C.empty:
        log.error("empty panel(s): M=%s C=%s", M.shape, C.shape)
        return 3
    log.info("M=%s C=%s", M.shape, C.shape)

    df = evaluate(M, C, args.window_days, args.refit_days, args.ridge_lambda,
                  args.min_binding_hours, args.standardize, args.std_floor)
    # Keep only scored weeks in the requested range (read window pulled extra).
    panel_tz = M.index.tz
    start_ts = pd.Timestamp(args.start, tz=panel_tz)
    df = df[df["score_start"] >= start_ts].reset_index(drop=True)
    if df.empty:
        log.error("no scored weeks in [%s, %s)", args.start, args.end)
        return 4

    out_dir = RUNS_ROOT / args.run_id / "ibp"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "eval.csv"
    df.to_csv(out_path, index=False)

    pd.set_option("display.width", 200)
    show = df.drop(columns=["score_end", "window_start"])
    print(show.to_string(index=False, float_format=lambda v: f"{v:8.3f}"))
    print(f"\n=== eval over {len(df)} weeks "
          f"(window {args.window_days}d, refit {args.refit_days}d, "
          f"λ {args.ridge_lambda:g}, min_hours {args.min_binding_hours}) ===")
    print(f"OOS pooled R2   (oracle μ, the ceiling) : {df.oos_pooled_r2.mean():.3f}")
    print(f"in-sample R2    (what the pipeline reports) : {df.is_pooled_r2.mean():.3f}")
    print(f"rank-Spearman   : {df.rank_spearman.mean():.3f}")
    print(f"sign-agree      : {df.sign_agree.mean():.3f}")
    print(f"top-decile hit  : {df.topdecile_hit.mean():.3f}")
    print(f"coverage        : {df.coverage.mean():.3f}")
    print(f"SF stability    (disjoint 60d) : {df.sf_stability.mean():.3f}")
    log.info("wrote %s", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
