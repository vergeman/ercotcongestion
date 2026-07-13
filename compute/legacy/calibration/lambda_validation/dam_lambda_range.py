"""
NP4-523-CD (dam_system_lambda) range check for 0049 S4.3.

Reads the full analysis window (2025-01-01 through 2026-06-30) from
`dam_system_lambda`, reports the overall distribution + histogram, and
prints the top/bottom outlier hours so we can hand-check them against known
stress dates (winter storm, negative-price wind events, etc.).

The plan hypothesis: baseline system λ sits around $20-60/MWh; stress hours
spike well above; occasional negatives from wind gluts. This script only
reports — the pass/fail interpretation is recorded in `docs/dam_lambda_range.md`.

Usage:
    docker compose run --rm compute python \\
        -m compute.legacy.calibration.lambda_validation.dam_lambda_range
    docker compose run --rm compute python \\
        -m compute.legacy.calibration.lambda_validation.dam_lambda_range \\
        --start 2025-01-01 --end 2026-07-01 --out docs/dam_lambda_range.md
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

from compute.config import PG_DSN

DEFAULT_START = "2025-01-01"
DEFAULT_END   = "2026-07-01"
DEFAULT_OUT   = Path("/compute/calibration/lambda_validation/dam_lambda_range.md")

# Baseline band the plan is checking against.
BASELINE_LO = 20.0
BASELINE_HI = 60.0

# Bucket edges for the histogram column of the report.
BUCKETS = [
    ("<0",         -np.inf,  0.0),
    ("0-20",         0.0,   20.0),
    ("20-60 (baseline)", 20.0, 60.0),
    ("60-100",      60.0,  100.0),
    ("100-500",    100.0,  500.0),
    ("500-2000",   500.0, 2000.0),
    (">=2000",    2000.0,  np.inf),
]


def _fetch(conn, start: datetime, end: datetime) -> pd.Series:
    """Hourly system_lambda over [start, end) as an indexed Series."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT interval_ts, system_lambda
        FROM dam_system_lambda
        WHERE interval_ts >= %s AND interval_ts < %s AND dst_flag = FALSE
        ORDER BY interval_ts
        """,
        (start, end),
    )
    rows = cur.fetchall()
    idx = pd.DatetimeIndex([r[0] for r in rows])
    vals = np.array([float(r[1]) for r in rows])
    return pd.Series(vals, index=idx, name="system_lambda")


def _histogram(s: pd.Series) -> list[tuple[str, int, float]]:
    n = len(s)
    out: list[tuple[str, int, float]] = []
    for label, lo, hi in BUCKETS:
        mask = (s >= lo) & (s < hi)
        cnt = int(mask.sum())
        pct = 100.0 * cnt / n if n else 0.0
        out.append((label, cnt, pct))
    return out


def _dist_stats(s: pd.Series) -> dict:
    return {
        "n":    int(s.shape[0]),
        "mean": float(s.mean()),
        "std":  float(s.std(ddof=1)),
        "min":  float(s.min()),
        "p5":   float(s.quantile(0.05)),
        "p25":  float(s.quantile(0.25)),
        "p50":  float(s.quantile(0.50)),
        "p75":  float(s.quantile(0.75)),
        "p95":  float(s.quantile(0.95)),
        "p99":  float(s.quantile(0.99)),
        "max":  float(s.max()),
    }


def _cluster_by_day(ts_values: list[tuple[pd.Timestamp, float]]) -> list[dict]:
    """Group consecutive rows by (UTC) day to keep the outlier table readable.
    Returns per-day rollups: date, hour_count, min λ, max λ, first/last ts."""
    if not ts_values:
        return []
    by_day: dict[str, list[tuple[pd.Timestamp, float]]] = {}
    for ts, v in ts_values:
        day = ts.strftime("%Y-%m-%d")
        by_day.setdefault(day, []).append((ts, v))
    rows: list[dict] = []
    for day, items in sorted(by_day.items()):
        items.sort()
        vals = [v for _, v in items]
        rows.append({
            "date":  day,
            "n":     len(items),
            "min_l": min(vals),
            "max_l": max(vals),
            "first": items[0][0].isoformat(),
            "last":  items[-1][0].isoformat(),
        })
    return rows


def _fmt(v, spec=".2f"):
    if v is None:
        return "-"
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return "nan"
    return format(v, spec)


def _render_md(
    s: pd.Series,
    stats: dict,
    hist: list[tuple[str, int, float]],
    high_days: list[dict],
    low_days: list[dict],
    top_hours: list[tuple[pd.Timestamp, float]],
    bot_hours: list[tuple[pd.Timestamp, float]],
    start: datetime,
    end: datetime,
    high_threshold: float,
    low_threshold: float,
) -> str:
    baseline_mask = (s >= BASELINE_LO) & (s < BASELINE_HI)
    baseline_frac = 100.0 * float(baseline_mask.mean())
    neg_frac      = 100.0 * float((s < 0).mean())
    high_frac     = 100.0 * float((s >= high_threshold).mean())

    lines: list[str] = []
    lines.append("# NP4-523-CD range check (0049 S4.3)\n")
    lines.append(
        f"Hourly DAM system λ (`dam_system_lambda`) over "
        f"`{start.strftime('%Y-%m-%d')}` .. `{end.strftime('%Y-%m-%d')}` "
        f"(exclusive end; `dst_flag=false` only).\n"
    )
    lines.append(f"* Rows: {stats['n']}")
    lines.append(f"* Baseline band ${BASELINE_LO:.0f}-${BASELINE_HI:.0f}: "
                 f"{baseline_frac:.1f}% of hours")
    lines.append(f"* Negative-λ hours: {neg_frac:.2f}%")
    lines.append(f"* Stress hours (λ ≥ ${high_threshold:.0f}): "
                 f"{high_frac:.2f}%\n")

    lines.append("## Distribution\n")
    lines.append("| n | mean | std | min | p5 | p25 | p50 | p75 | p95 | p99 | max |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    lines.append(
        f"| {stats['n']} | {_fmt(stats['mean'])} | {_fmt(stats['std'])} | "
        f"{_fmt(stats['min'])} | {_fmt(stats['p5'])} | {_fmt(stats['p25'])} | "
        f"{_fmt(stats['p50'])} | {_fmt(stats['p75'])} | {_fmt(stats['p95'])} | "
        f"{_fmt(stats['p99'])} | {_fmt(stats['max'])} |\n"
    )

    lines.append("## Histogram\n")
    lines.append("| bucket ($/MWh) | hours | % |")
    lines.append("|---|---:|---:|")
    for label, cnt, pct in hist:
        lines.append(f"| {label} | {cnt} | {_fmt(pct)}% |")
    lines.append("")

    lines.append(f"## High-λ clusters (λ ≥ ${high_threshold:.0f})\n")
    if high_days:
        lines.append("| date (UTC) | hours | min λ | max λ | window |")
        lines.append("|---|---:|---:|---:|---|")
        for d in high_days:
            lines.append(
                f"| {d['date']} | {d['n']} | {_fmt(d['min_l'])} | "
                f"{_fmt(d['max_l'])} | {d['first']} .. {d['last']} |"
            )
    else:
        lines.append("_No hours above threshold._")
    lines.append("")

    lines.append(f"## Negative-λ clusters (λ ≤ ${low_threshold:.0f})\n")
    if low_days:
        lines.append("| date (UTC) | hours | min λ | max λ | window |")
        lines.append("|---|---:|---:|---:|---|")
        for d in low_days:
            lines.append(
                f"| {d['date']} | {d['n']} | {_fmt(d['min_l'])} | "
                f"{_fmt(d['max_l'])} | {d['first']} .. {d['last']} |"
            )
    else:
        lines.append("_No hours below threshold._")
    lines.append("")

    lines.append("## Top 10 hours by λ\n")
    lines.append("| interval_ts (UTC) | λ ($/MWh) |")
    lines.append("|---|---:|")
    for ts, v in top_hours:
        lines.append(f"| {ts.isoformat()} | {_fmt(v)} |")
    lines.append("")

    lines.append("## Bottom 10 hours by λ\n")
    lines.append("| interval_ts (UTC) | λ ($/MWh) |")
    lines.append("|---|---:|")
    for ts, v in bot_hours:
        lines.append(f"| {ts.isoformat()} | {_fmt(v)} |")
    lines.append("")

    lines.append("## Interpretation\n")
    lines.append(
        "The plan hypothesis is that NP4-523-CD sits in a $20-60/MWh baseline "
        "with wider excursions during grid stress. Compare the numbers above "
        "against that expectation and record the disposition inline before "
        "rolling the summary into `docs/congestion_stats.md`."
    )
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=DEFAULT_START,
                    help=f"UTC start (inclusive). Default: {DEFAULT_START}.")
    ap.add_argument("--end",   default=DEFAULT_END,
                    help=f"UTC end (exclusive). Default: {DEFAULT_END}.")
    ap.add_argument("--high-threshold", type=float, default=100.0,
                    help="λ threshold for high-cluster table (default: 100).")
    ap.add_argument("--low-threshold",  type=float, default=0.0,
                    help="λ threshold for negative-cluster table (default: 0).")
    ap.add_argument("--top-n", type=int, default=10,
                    help="Rows in the top/bottom hour tables (default: 10).")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"Markdown output path. Default: {DEFAULT_OUT}.")
    args = ap.parse_args()

    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end   = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc)

    with psycopg.connect(PG_DSN) as conn:
        s = _fetch(conn, start, end)
    if s.empty:
        raise SystemExit(f"no rows in {start}..{end}")

    stats = _dist_stats(s)
    hist  = _histogram(s)

    high_mask = s >= args.high_threshold
    low_mask  = s <= args.low_threshold
    high_days = _cluster_by_day(list(zip(s[high_mask].index, s[high_mask].values)))
    low_days  = _cluster_by_day(list(zip(s[low_mask].index,  s[low_mask].values)))

    top_hours = list(s.nlargest(args.top_n).items())
    bot_hours = list(s.nsmallest(args.top_n).items())

    md = _render_md(
        s=s, stats=stats, hist=hist,
        high_days=high_days, low_days=low_days,
        top_hours=top_hours, bot_hours=bot_hours,
        start=start, end=end,
        high_threshold=args.high_threshold,
        low_threshold=args.low_threshold,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md)
    print(f"wrote {args.out}  (n={stats['n']}  p50=${stats['p50']:.2f}  "
          f"max=${stats['max']:.2f})")


if __name__ == "__main__":
    main()
