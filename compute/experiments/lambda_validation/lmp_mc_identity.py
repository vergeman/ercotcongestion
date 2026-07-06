"""
LMP − system_λ ≈ modeled_congestion identity check (plan/0058 acceptance).

DC-OPF identity: LMP_b = system_λ + congestion_b + losses_b. For a lossless
DC model the losses term is zero, so LMP_b − system_λ should equal
modeled_congestion_b exactly. In practice small residuals appear from
solver tolerances, per-snapshot marginal-generator switching, and rounding
in the writeout, so we accept a "few $/MWh" tolerance.

For each snapshot in a window we compute r_b = LMP_b − system_λ − MC_b
per bus, then report per-snapshot summary stats (median |r|, P95 |r|, max
|r|, count of buses exceeding a 5 $/MWh threshold). The identity is
considered upheld if median |r| stays under 1 $/MWh and P95 stays under
5 $/MWh across the window.

Usage:
    docker compose run --rm compute python \\
        -m compute.experiments.lambda_validation.lmp_mc_identity \\
        --start 2025-01-03 --end 2025-01-06
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import psycopg

from compute.config import PG_DSN

# The identity holds against whichever system_λ estimator the pipeline used
# when writing snapshot_meta. `system_lambda_merit_order` is the active ref
# (ACTIVE_ERCOT_REF = "system_lambda"); if the model was run against a
# different estimator, swap this column via --lambda-col.
DEFAULT_LAMBDA_COL = "system_lambda_merit_order"

# Tolerance thresholds. "A few $/MWh" per the plan.
MEDIAN_TOL = 1.0
P95_TOL = 5.0


def _coerce_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _fetch(conn, start: datetime, end: datetime, lambda_col: str) -> pd.DataFrame:
    """Join bus_snapshots and snapshot_meta over [start, end)."""
    sql = f"""
        SELECT
            b.interval_ts,
            b.bus_id,
            b.lmp,
            b.modeled_congestion,
            m.{lambda_col} AS system_lambda
        FROM bus_snapshots b
        JOIN snapshot_meta m USING (interval_ts)
        WHERE b.interval_ts >= %s AND b.interval_ts < %s
          AND m.status = 'ok'
          AND b.lmp IS NOT NULL
          AND b.modeled_congestion IS NOT NULL
          AND m.{lambda_col} IS NOT NULL
        ORDER BY b.interval_ts, b.bus_id
    """
    with conn.cursor() as cur:
        cur.execute(sql, (start, end))
        rows = cur.fetchall()
    return pd.DataFrame(
        rows, columns=["interval_ts", "bus_id", "lmp", "mc", "system_lambda"]
    )


def _per_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    """Residual r_b = LMP_b − system_λ − MC_b, summarized per snapshot."""
    df = df.copy()
    df["r"] = df["lmp"].astype(float) - df["system_lambda"].astype(float) - df["mc"].astype(float)
    grouped = df.groupby("interval_ts")["r"]
    out = pd.DataFrame({
        "n_buses":   grouped.size(),
        "median_abs": grouped.apply(lambda s: float(np.median(np.abs(s)))),
        "p95_abs":   grouped.apply(lambda s: float(np.quantile(np.abs(s), 0.95))),
        "max_abs":   grouped.apply(lambda s: float(np.max(np.abs(s)))),
        "n_over_5":  grouped.apply(lambda s: int((np.abs(s) > 5.0).sum())),
    })
    return out.reset_index()


def _verdict(summary: pd.DataFrame) -> str:
    med = summary["median_abs"].max()
    p95 = summary["p95_abs"].max()
    if med <= MEDIAN_TOL and p95 <= P95_TOL:
        return f"PASS  (worst median |r| = {med:.3f}, worst P95 |r| = {p95:.3f})"
    return f"FAIL  (worst median |r| = {med:.3f}, worst P95 |r| = {p95:.3f})"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", required=True, help="ISO date/datetime UTC (inclusive)")
    p.add_argument("--end", required=True, help="ISO date/datetime UTC (exclusive)")
    p.add_argument("--lambda-col", default=DEFAULT_LAMBDA_COL,
                   help=f"snapshot_meta column carrying system λ (default: {DEFAULT_LAMBDA_COL})")
    p.add_argument("--limit-print", type=int, default=10,
                   help="How many worst-residual snapshots to print (default: 10)")
    args = p.parse_args()

    start = _coerce_utc(datetime.fromisoformat(args.start))
    end = _coerce_utc(datetime.fromisoformat(args.end))

    with psycopg.connect(PG_DSN) as conn:
        df = _fetch(conn, start, end, args.lambda_col)

    if df.empty:
        print(f"no rows in window {start} .. {end}")
        return

    summary = _per_snapshot(df)
    print(f"window: {start} .. {end}")
    print(f"snapshots: {len(summary)}   buses/snapshot median: {int(summary['n_buses'].median())}")
    print()
    print(f"identity residual r_b = LMP_b - λ - MC_b   (lambda_col = {args.lambda_col})")
    print(summary.describe(percentiles=[0.5, 0.9, 0.99])
                  [["median_abs", "p95_abs", "max_abs", "n_over_5"]].to_string())
    print()
    print(_verdict(summary))
    print()
    worst = summary.sort_values("p95_abs", ascending=False).head(args.limit_print)
    print(f"worst {len(worst)} snapshots by P95 |r|:")
    print(worst.to_string(index=False))


if __name__ == "__main__":
    main()
