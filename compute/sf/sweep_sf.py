"""Hyperparameter sweep over (window, refit, ridge-λ), ranked on OOS metrics.

Selection target changed (S1.4): the old sweep sorted on ``bp_max`` and reported
in-sample ``mean_r2`` — an in-sample DOF curve, monotone in ``n_kept``, i.e.
cosmetics. The config was never picked against anything held out. This version
ranks on the honest out-of-window metrics from ``compute.sf.eval`` (default the
oracle-μ pooled R², the SF map's ceiling), so the operating point is chosen on
what the pivot actually needs.

Architecture change: panels are loaded from Postgres ONCE and every combo is
scored in-process via ``eval.evaluate`` (was: a fresh ``runner`` subprocess +
DB re-query per combo). With the grid the pivot mandates — window ∈
{60,120,240,365}, refit ∈ {7,14}, λ across its effective range — reloading a
multi-year panel per combo was the dominant cost.

After ranking, the SF drift curve ``corr(SF_t, SF_{t+Δ})`` is emitted for the
winning config, out to Δ = window (below that the fits overlap and the curve
measures overlap, not drift).

``--rho-min`` (S2 / plan 0083) adds the collinear-grouping axis. Put ``none`` in
the grid to sweep the ungrouped arm alongside the grouped ones, so the baseline
is measured on identical weeks and panels rather than quoted from another run.
``--control`` adds ``sf_stability_proj``, the projected-ungrouped baseline that
R3's stability bar is actually judged against.

    docker compose run --rm compute \\
      python -m compute.sf.sweep_sf \\
        --start 2025-01-01 --end 2026-01-01 \\
        [--window-days 60,120,240,365] [--refit-days 7,14] \\
        [--ridge-lambda 0.1,1,10,100,1000] [--rank-by oos_pooled_r2] \\
        [--rho-min none,0.7,0.8,0.9 --control] \\
        [--out /compute/sf/sf_sweep_summary.csv]
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta

import pandas as pd
import psycopg

from compute.config import PG_DSN
from compute.sf.eval import evaluate, sf_decay
from compute.sf.panels import load_congestion_panel, load_shadow_prices

log = logging.getLogger("compute.sf.sweep_sf")

# Grids the pivot mandates: window/refit/λ across their effective ranges.
# λ old default 0.1 vs XᵀX diag ≈1440 — decorative; extend up to where it bites.
DEFAULT_WINDOW_DAYS = "60,120,240,365"
DEFAULT_REFIT_DAYS = "7,14"
DEFAULT_RIDGE_LAMBDA = "0.1,1,10,100,1000"
DEFAULT_STD_FLOOR = "100"
DEFAULT_MIN_BINDING_HOURS = "25"
DEFAULT_RHO_MIN = "none"

# Means reported per combo; ranked on --rank-by. Higher is better for all.
METRIC_COLS = [
    "oos_pooled_r2", "is_pooled_r2", "rank_spearman", "sign_agree",
    "topdecile_hit", "coverage", "sf_stability", "sf_stability_proj",
    "n_constraints", "n_groups", "group_churn",
]


def _ints(csv: str) -> list[int]:
    return [int(x) for x in csv.split(",") if x.strip()]


def _floats(csv: str) -> list[float]:
    return [float(x) for x in csv.split(",") if x.strip()]


def _rhos(csv: str) -> list[float | None]:
    """``none`` is the ungrouped arm — the baseline every grouped row is judged
    against, swept in the same pass so it sees identical weeks and panels."""
    out: list[float | None] = []
    for tok in csv.split(","):
        tok = tok.strip()
        if not tok:
            continue
        out.append(None if tok.lower() in {"none", "off", "ungrouped"} else float(tok))
    return out


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _summarize(df: pd.DataFrame) -> dict:
    """Mean each metric over the scored weeks; median n_kept."""
    out = {c: float(df[c].mean()) for c in METRIC_COLS}
    out["median_n_kept"] = float(df["n_kept"].median())
    out["n_weeks"] = int(len(df))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--start", type=_parse_date, required=True,
                   help="Inclusive first day to score (YYYY-MM-DD).")
    p.add_argument("--end", type=_parse_date, required=True,
                   help="Exclusive last day to score (YYYY-MM-DD).")
    p.add_argument("--window-days", default=DEFAULT_WINDOW_DAYS)
    p.add_argument("--refit-days", default=DEFAULT_REFIT_DAYS)
    p.add_argument("--ridge-lambda", default=DEFAULT_RIDGE_LAMBDA)
    p.add_argument("--std-floor", default=DEFAULT_STD_FLOOR)
    p.add_argument("--min-binding-hours", default=DEFAULT_MIN_BINDING_HOURS)
    p.add_argument("--rho-min", default=DEFAULT_RHO_MIN,
                   help="Collinear-grouping thresholds to sweep (S2 / plan 0083). "
                        "`none` = the ungrouped arm; include it to get the "
                        "baseline from the same weeks and panels.")
    p.add_argument("--control", action="store_true",
                   help="Also emit sf_stability_proj per grouped combo: the "
                        "ungrouped SF projected into that combo's group "
                        "row-space. This is the baseline R3's stability bar is "
                        "measured against — a raw grouped-vs-ungrouped delta "
                        "would credit grouping for merely being a smaller "
                        "matrix. ~2x cost.")
    p.add_argument("--per-week-out", type=str, default=None,
                   help="Also write the per-week rows for every combo (needed "
                        "for the pre/post-RTC+B split).")
    p.add_argument("--rank-by", default="oos_pooled_r2", choices=METRIC_COLS,
                   help="OOS metric to sort by (default oos_pooled_r2).")
    p.add_argument("--no-decay", dest="emit_decay", action="store_false",
                   help="Skip the SF decay curve for the winning config.")
    p.add_argument("--out", type=str, default=None,
                   help="CSV output path; prints to stdout if omitted.")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    windows = _ints(args.window_days)
    refits = _ints(args.refit_days)
    lambdas = _floats(args.ridge_lambda)
    floors = _floats(args.std_floor)
    min_hours_list = _ints(args.min_binding_hours)
    rhos = _rhos(args.rho_min)
    combos = [
        (w, r, lam, sf, mh, rho)
        for w in windows for r in refits for lam in lambdas
        for sf in floors for mh in min_hours_list for rho in rhos
    ]

    # Load panels ONCE, with enough warmup behind `start` for the largest
    # window's disjoint-stability pair (2×window). evaluate/sf_decay reindex.
    read_start = args.start - timedelta(days=2 * max(windows))
    log.info("loading panels once: read=[%s, %s), %d combos",
             read_start, args.end, len(combos))
    with psycopg.connect(PG_DSN) as conn:
        M = load_shadow_prices(conn, read_start, args.end)
        C = load_congestion_panel(conn, read_start, args.end)
    if M.empty or C.empty:
        log.error("empty panel(s): M=%s C=%s", M.shape, C.shape)
        return 3
    log.info("M=%s C=%s", M.shape, C.shape)

    start_ts = pd.Timestamp(args.start, tz=M.index.tz)
    day = pd.Timedelta(days=1)

    # One clustering tree per (window bounds), reused across every rho in the
    # grid — the tree depends on the window, not on the threshold. Without this
    # the sweep rebuilds a ~4,000-column correlation per rho per refit and the
    # rho axis alone would dominate the runtime.
    linkage_cache: dict = {}

    rows: list[dict] = []
    per_week: list[pd.DataFrame] = []
    for i, (w, r, lam, floor, mh, rho) in enumerate(combos, 1):
        # Trim to this window's warmup so small windows don't fit the whole
        # loaded history (compute stays proportional to the window).
        lo = start_ts - 2 * w * day
        Mc = M.loc[M.index >= lo]
        Cc = C.loc[C.index >= lo]
        log.info("[%d/%d] window=%d refit=%d λ=%g floor=%g min_hours=%d rho=%s",
                 i, len(combos), w, r, lam, floor, mh, rho)
        df = evaluate(Mc, Cc, window_days=w, refit_days=r, lam=lam,
                      min_hours=mh, standardize=True, std_floor=floor,
                      rho_min=rho, control=args.control and rho is not None,
                      linkage_cache=linkage_cache, score_from=start_ts)
        if df.empty:
            log.warning("  no scored weeks; skipping")
            continue
        params = {
            "window_days": w, "refit_days": r, "ridge_lambda": lam,
            "std_floor": floor, "min_binding_hours": mh,
            "rho_min": rho if rho is not None else "ungrouped",
        }
        rows.append({**params, **_summarize(df)})
        if args.per_week_out:
            per_week.append(df.assign(**params))

    if not rows:
        log.error("no combos produced scored weeks")
        return 1

    if args.per_week_out:
        pd.concat(per_week, ignore_index=True).to_csv(args.per_week_out, index=False)
        log.info("wrote %s", args.per_week_out)

    summary = pd.DataFrame(rows).sort_values(args.rank_by, ascending=False)
    with pd.option_context("display.max_rows", None, "display.width", None,
                           "display.max_columns", None):
        print(summary.to_string(index=False, float_format=lambda v: f"{v:.3f}"))

    if args.out:
        summary.to_csv(args.out, index=False)
        log.info("wrote %s", args.out)

    if args.emit_decay:
        top = summary.iloc[0]
        w = int(top.window_days)
        lo = start_ts - 2 * w * day
        rho = None if top.rho_min == "ungrouped" else float(top.rho_min)
        # Δ must reach the window: below it the two fits share hours and the
        # curve reports overlap, not drift.
        deltas = tuple(sorted({7, 14, 30, 60, w}))
        decay = sf_decay(M.loc[M.index >= lo], C.loc[C.index >= lo],
                         window_days=w, deltas_days=deltas,
                         lam=float(top.ridge_lambda),
                         min_hours=int(top.min_binding_hours),
                         std_floor=float(top.std_floor),
                         rho_min=rho, linkage_cache=linkage_cache)
        print(f"\n=== SF decay curve — winning config "
              f"(window={w}, λ={top.ridge_lambda:g}, rho_min={top.rho_min}) ===")
        print(decay.to_string(index=False, float_format=lambda v: f"{v:.3f}"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
