"""
Cross-method reference-price comparison (0068).

Reads per-method model-side `reference_prices` and `load_shed_mw` from
`snapshot_meta` and joins the published ERCOT NP4-523-CD `system_lambda`
from `dam_system_lambda` on `interval_ts`. Reports per-method distribution,
pairwise Pearson correlation, and delta stats vs the fixed model reference
(`kkt_perbus`) over the matched snapshot set.

Methods compared:

    hub_avg, load_weighted, gen_weighted, lmp_median,
    system_lambda (ERCOT NP4-523-CD; published, no model analogue),
    system_lambda_kkt (model-side KKT clean-bus median),
    system_lambda_merit_order (model-side copper-plate via merit-order).
    kkt_perbus

`simple_mean` is skipped — it is the trivial mean(lmps) baseline, not a λ
approximation, and only exists as a centering sanity check inside the
congestion module.

Usage:
    docker compose run --rm compute python \\
        -m compute.calibration.lambda_validation.cross_method_compare \\
        --start 2025-01-01 --end 2026-07-01
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

from compute.config import PG_DSN

# Model-side per-method reference-price series live under
# snapshot_meta.reference_prices (jsonb). ERCOT-side `system_lambda` is the
# NP4-523-CD published λ from dam_system_lambda.
MODEL_METHODS = (
    "hub_avg",
    "load_weighted",
    "gen_weighted",
    "lmp_median",
    "system_lambda_kkt",
    "system_lambda_merit_order",
    "kkt_perbus"
)
ERCOT_METHOD = "zone_local_spp"

DEFAULT_START = "2025-01-01"
DEFAULT_END   = "2026-01-01"
DEFAULT_OUT   = Path("/compute/calibration/lambda_validation/cross_method.md")


def _coerce_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _fetch_model_rows(
    conn, start: datetime, end: datetime
) -> tuple[dict[datetime, dict[str, float | None]], dict[datetime, float]]:
    """One round trip: reference_prices (jsonb) and load_shed_mw over the
    ok-status window. Returns (model_by_ts, shed_by_ts)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT interval_ts, reference_prices, load_shed_mw
            FROM snapshot_meta
            WHERE status = 'ok' AND interval_ts BETWEEN %s AND %s
            ORDER BY interval_ts
            """,
            (start, end),
        )
        model_by_ts: dict[datetime, dict[str, float | None]] = {}
        shed_by_ts: dict[datetime, float] = {}
        for ts, refs, shed in cur.fetchall():
            model_by_ts[ts] = refs or {}
            shed_by_ts[ts] = float(shed or 0.0)
    return model_by_ts, shed_by_ts


def _fetch_system_lambda(
    conn, ts_list: list[datetime]
) -> dict[datetime, float]:
    """dam_system_lambda.system_lambda per ts. DST-safe."""
    if not ts_list:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (interval_ts) interval_ts, system_lambda
            FROM dam_system_lambda
            WHERE interval_ts = ANY(%s)
            ORDER BY interval_ts, dst_flag ASC
            """,
            (ts_list,),
        )
        return {ts: float(v) for ts, v in cur.fetchall() if v is not None}


def _build_frame(
    model_by_ts: dict[datetime, dict[str, float | None]],
    system_lambda_by_ts: dict[datetime, float],
    shed_by_ts:  dict[datetime, float],
) -> tuple[pd.DataFrame, list[datetime]]:
    """Wide (ts × method) DataFrame. Only timestamps present on the model
    side are used (that is the analysis window); ERCOT `system_lambda`
    joins on ts and is NaN where absent."""
    rows: dict[datetime, dict[str, float]] = {}
    for ts, mrefs in model_by_ts.items():
        row: dict[str, float] = {}
        for m in MODEL_METHODS:
            v = mrefs.get(m) if mrefs else None
            row[m] = float(v) if v is not None else np.nan
        v = system_lambda_by_ts.get(ts)
        row[ERCOT_METHOD] = float(v) if v is not None else np.nan
        rows[ts] = row
    ts_order = sorted(rows)
    df = pd.DataFrame([rows[t] for t in ts_order], index=pd.Index(ts_order, name="ts"))
    shed_ts = [t for t in ts_order if shed_by_ts.get(t, 0.0) > 0.0]
    return df, shed_ts


def _dist_stats(s: pd.Series) -> dict:
    s = s.dropna()
    if s.empty:
        return {
            "n": 0, "mean": float("nan"), "std": float("nan"),
            "min": float("nan"), "p5": float("nan"), "p50": float("nan"),
            "p95": float("nan"), "max": float("nan"),
        }
    return {
        "n":    int(s.shape[0]),
        "mean": float(s.mean()),
        "std":  float(s.std(ddof=1)) if s.shape[0] > 1 else 0.0,
        "min":  float(s.min()),
        "p5":   float(s.quantile(0.05)),
        "p50":  float(s.quantile(0.50)),
        "p95":  float(s.quantile(0.95)),
        "max":  float(s.max()),
    }


def _pairwise_corr(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Pearson pairwise-complete over the requested columns. Preserves the
    caller's column order in the result."""
    return df[cols].corr(method="pearson", min_periods=3).reindex(index=cols, columns=cols)


def _fmt(v, spec=".2f"):
    if v is None:
        return "-"
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return "nan"
    return format(v, spec)


def _render_md(
    df: pd.DataFrame,
    stats_all: dict[str, dict],
    stats_noshed: dict[str, dict],
    corr_all: pd.DataFrame,
    corr_noshed: pd.DataFrame,
    ref_col: str,
    ref_delta: dict[str, dict],
    shed_ts: list,
    n_clean: int,
    start: datetime,
    end: datetime,
) -> str:
    cols = list(df.columns)
    lines: list[str] = []
    lines.append("# λ cross-method comparison\n")
    lines.append(
        f"Sample: **{df.shape[0]}** ok snapshots over "
        f"`{start.isoformat()}` .. `{end.isoformat()}` (model side, "
        f"`snapshot_meta.reference_prices`). Shed-tainted snapshots "
        f"(`load_shed_mw > 0`): **{len(shed_ts)}**; shed-clean subset: "
        f"**{n_clean}**. ERCOT `system_lambda` (NP4-523-CD) joined from "
        f"`dam_system_lambda` by ts.\n"
    )
    lines.append(
        "`kkt_perbus` is the fixed model reference. Every other "
        "column is an approximation compared against it. "
    )

    def _stats_table(stats: dict[str, dict], title: str) -> list[str]:
        out = [f"## {title}\n",
               "| method | n | mean | std | min | p5 | p50 | p95 | max |",
               "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for m in cols:
            s = stats[m]
            out.append(
                f"| `{m}` | {s['n']} | {_fmt(s['mean'])} | {_fmt(s['std'])} | "
                f"{_fmt(s['min'])} | {_fmt(s['p5'])} | {_fmt(s['p50'])} | "
                f"{_fmt(s['p95'])} | {_fmt(s['max'])} |"
            )
        out.append("")
        return out

    lines.extend(_stats_table(stats_all, "Distribution — all snapshots"))
    if n_clean >= 5:
        lines.extend(_stats_table(stats_noshed,
                                  "Distribution — shed-clean subset"))

    def _corr_table(corr: pd.DataFrame, title: str) -> list[str]:
        out = [f"## {title}\n"]
        header = "| | " + " | ".join(f"`{c}`" for c in cols) + " |"
        sep    = "|---|" + "|".join("---:" for _ in cols) + "|"
        out.append(header)
        out.append(sep)
        for r in cols:
            row = [f"`{r}`"]
            for c in cols:
                v = corr.at[r, c] if r in corr.index and c in corr.columns else float("nan")
                row.append(_fmt(v, ".3f"))
            out.append("| " + " | ".join(row) + " |")
        out.append("")
        return out

    lines.extend(_corr_table(corr_all,
                             "Pairwise Pearson correlation — all snapshots"))
    if n_clean >= 5:
        lines.extend(_corr_table(corr_noshed,
                                 "Pairwise Pearson correlation — shed-clean subset"))
        lines.append(f"## Delta vs `{ref_col}` (fixed model reference)\n")
        lines.append(
            "Per-snapshot bias of each method against `merit_order` "
            "(`method - merit_order`). Positive = overstates λ vs the "
            "fixed model reference; negative = understates. Reported on "
            "the shed-clean subset — `merit_order` is only meaningful "
            "when no load was shed in Pass 1.\n"
        )
        lines.append(
            "| method | n | mean Δ | std Δ | p5 | p50 | p95 | mean\\|Δ\\| |"
        )
        lines.append(
            "|---|---:|---:|---:|---:|---:|---:|---:|"
        )
        for m in cols:
            if m == ref_col:
                continue
            s = ref_delta.get(m)
            if not s or s["n"] == 0:
                continue
            lines.append(
                f"| `{m}` | {s['n']} | {_fmt(s['mean'])} | {_fmt(s['std'])} | "
                f"{_fmt(s['p5'])} | {_fmt(s['p50'])} | {_fmt(s['p95'])} | "
                f"{_fmt(s['mean_abs'])} |"
            )
        lines.append("")

    lines.append("## Notes\n")
    lines.append(
        "* `simple_mean` is omitted — it is an unweighted `lmps.mean()`, "
        "the centering diagnostic used by `compute_congestion`, not a λ "
        "approximation."
    )
    lines.append(
        "* `system_lambda` join drops any snapshot missing from "
        "`dam_system_lambda` (n reported per method above)."
    )
    return "\n".join(lines) + "\n"


def _delta_stats(df: pd.DataFrame, ref_col: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    ref = df[ref_col]
    for m in df.columns:
        if m == ref_col:
            continue
        delta = (df[m] - ref).dropna()
        if delta.empty:
            out[m] = {
                "n": 0, "mean": float("nan"), "std": float("nan"),
                "p5": float("nan"), "p50": float("nan"), "p95": float("nan"),
                "mean_abs": float("nan"),
            }
            continue
        out[m] = {
            "n":        int(delta.shape[0]),
            "mean":     float(delta.mean()),
            "std":      float(delta.std(ddof=1)) if delta.shape[0] > 1 else 0.0,
            "p5":       float(delta.quantile(0.05)),
            "p50":      float(delta.quantile(0.50)),
            "p95":      float(delta.quantile(0.95)),
            "mean_abs": float(delta.abs().mean()),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=DEFAULT_START,
                    help=f"UTC start (inclusive). Default: {DEFAULT_START}.")
    ap.add_argument("--end", default=DEFAULT_END,
                    help=f"UTC end (inclusive). Default: {DEFAULT_END}.")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    start = _coerce_utc(datetime.fromisoformat(args.start))
    end   = _coerce_utc(datetime.fromisoformat(args.end))

    with psycopg.connect(PG_DSN) as conn:
        model_by_ts, shed_by_ts = _fetch_model_rows(conn, start, end)
        system_lambda_by_ts = _fetch_system_lambda(conn, list(model_by_ts.keys()))

    df, shed_ts = _build_frame(model_by_ts, system_lambda_by_ts, shed_by_ts)
    if df.empty:
        raise SystemExit(f"no ok snapshots in {start}..{end}")

    clean = df.drop(index=shed_ts, errors="ignore")

    cols = list(df.columns)
    stats_all    = {m: _dist_stats(df[m])    for m in cols}
    stats_noshed = {m: _dist_stats(clean[m]) for m in cols}
    corr_all     = _pairwise_corr(df, cols)
    corr_noshed  = _pairwise_corr(clean, cols)
    ref_delta    = _delta_stats(clean, "kkt_perbus")

    md = _render_md(
        df=df,
        stats_all=stats_all, stats_noshed=stats_noshed,
        corr_all=corr_all, corr_noshed=corr_noshed,
        ref_col="kkt_perbus",
        ref_delta=ref_delta,
        shed_ts=shed_ts,
        n_clean=clean.shape[0],
        start=start, end=end,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md)
    print(f"wrote {args.out}  (n_all={df.shape[0]}  n_shed_clean={clean.shape[0]})")


if __name__ == "__main__":
    main()
