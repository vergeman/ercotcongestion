"""
Cross-method reference-price comparison for 0049 S4.3.

Reads persisted `reference_prices` dicts from the v1-120-postfix backfill
(model side) and v1-120 backfill (ERCOT side) and reports per-method
distribution + pairwise correlation across the matched snapshot set. The
model-side sample is limited to the 120-snapshot v1-120 window until the
S4.1 canary clears the full-year re-backfill; the ERCOT-side pull adds the
published NP4-523-CD `system_lambda` for the same timestamps.

Methods compared (all in `reference_prices`):

    hub_avg, load_weighted, gen_weighted, lmp_median,
    system_lambda (ERCOT NP4-523-CD; published, no model analogue),
    system_lambda_kkt (model-side KKT clean-bus median),
    system_lambda_merit_order (model-side copper-plate via merit-order).

`simple_mean` is skipped — it is the trivial mean(lmps) baseline, not a λ
approximation, and only exists as a centering sanity check inside the
congestion module.

Usage:
    docker compose run --rm compute python \\
        -m compute.experiments.lambda_validation.cross_method_compare
    docker compose run --rm compute python \\
        -m compute.experiments.lambda_validation.cross_method_compare \\
        --model-results /compute/runs/v1-120-postfix/congestion/model_results.json.gz \\
        --ercot-results /compute/runs/v1-120/congestion/ercot_results.json.gz \\
        --out /compute/experiments/lambda_validation/cross_method.md
"""
import argparse
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd

# Model-side and ERCOT-side per-method reference-price series live under
# reference_prices[method]. On the ERCOT side, only `system_lambda` is
# populated (published λ) — model-only estimators come back as None.
MODEL_METHODS = (
    "hub_avg",
    "load_weighted",
    "gen_weighted",
    "lmp_median",
    "system_lambda_kkt",
    "system_lambda_merit_order",
)
ERCOT_METHOD = "system_lambda"     # NP4-523-CD, ERCOT side only

DEFAULT_MODEL = Path("/compute/runs/v1-120-postfix/congestion/model_results.json.gz")
DEFAULT_ERCOT = Path("/compute/runs/v1-120/congestion/ercot_results.json.gz")
DEFAULT_OUT   = Path("/compute/experiments/lambda_validation/cross_method.md")


def _load_json_gz(path: Path) -> list[dict]:
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt") as f:
        return json.load(f)


def _refs_by_ts(records: list[dict]) -> dict[str, dict[str, float | None]]:
    out: dict[str, dict[str, float | None]] = {}
    for r in records:
        if r.get("status") != "ok":
            continue
        refs = r.get("reference_prices") or {}
        out[r["ts"]] = refs
    return out


def _build_frame(
    model_by_ts: dict[str, dict],
    ercot_by_ts: dict[str, dict],
    shed_by_ts:  dict[str, float],
) -> tuple[pd.DataFrame, list[str]]:
    """Wide (ts × method) DataFrame. Only timestamps present on the model
    side are used (that is the analysis window); ERCOT `system_lambda`
    joins on ts and is NaN where absent."""
    rows: dict[str, dict[str, float]] = {}
    for ts, mrefs in model_by_ts.items():
        row: dict[str, float] = {}
        for m in MODEL_METHODS:
            v = mrefs.get(m) if mrefs else None
            row[m] = float(v) if v is not None else np.nan
        erefs = ercot_by_ts.get(ts) or {}
        v = erefs.get(ERCOT_METHOD)
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
    shed_ts: list[str],
    n_clean: int,
) -> str:
    cols = list(df.columns)
    lines: list[str] = []
    lines.append("# λ cross-method comparison (0049 S4.3)\n")
    lines.append(
        f"Sample: **{df.shape[0]}** snapshots from v1-120-postfix "
        f"(model side, post-shed / post-k-nearest). Shed-tainted snapshots "
        f"(Pass-1 `load_shed_mw > 0`): **{len(shed_ts)}**; shed-clean "
        f"subset: **{n_clean}**. ERCOT `system_lambda` (NP4-523-CD) joined "
        f"from the v1-120 ercot_results by ts.\n"
    )
    lines.append(
        "`system_lambda_merit_order` is the fixed model reference — the "
        "exact copper-plate λ recovered by economic dispatch. Every other "
        "column is an approximation compared against it. `system_lambda` "
        "(NP4-523-CD) is the real ERCOT-published λ and the closest "
        "external validator we have.\n"
    )
    lines.append(
        "The v1-120 sample is a summer-peak stress set, so essentially all "
        "snapshots hit shed and the shed-clean subset is not "
        "statistically meaningful in this window. It is reported anyway so "
        "the code is ready for the full-year re-backfill; interpret with "
        "sample size in mind.\n"
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
        "* Model-side sample is the v1-120 canary window (post-shed-fix, "
        "post-k-nearest). Full-year re-backfill will re-run this table."
    )
    lines.append(
        "* `system_lambda` join drops any snapshot missing from the ERCOT "
        "side (n reported per method above)."
    )
    return "\n".join(lines) + "\n"


def _shed_map(records: list[dict]) -> dict[str, float]:
    """ts -> Pass-1 load_shed_mw for the model-side records (0.0 if key
    missing / record errored). Used to build the shed-clean subset."""
    return {
        r["ts"]: float(r.get("load_shed_mw") or 0.0)
        for r in records
        if r.get("status") == "ok"
    }


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
    ap.add_argument("--model-results", type=Path, default=DEFAULT_MODEL)
    ap.add_argument("--ercot-results", type=Path, default=DEFAULT_ERCOT)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    model_recs = _load_json_gz(args.model_results)
    ercot_recs = _load_json_gz(args.ercot_results)

    model_by_ts = _refs_by_ts(model_recs)
    ercot_by_ts = _refs_by_ts(ercot_recs)
    shed_by_ts  = _shed_map(model_recs)

    df, shed_ts = _build_frame(model_by_ts, ercot_by_ts, shed_by_ts)
    if df.empty:
        raise SystemExit("no matched model-side records")

    clean = df.drop(index=shed_ts, errors="ignore")

    cols = list(df.columns)
    stats_all    = {m: _dist_stats(df[m])    for m in cols}
    stats_noshed = {m: _dist_stats(clean[m]) for m in cols}
    corr_all     = _pairwise_corr(df, cols)
    corr_noshed  = _pairwise_corr(clean, cols)
    ref_delta    = _delta_stats(clean, "system_lambda_merit_order")

    md = _render_md(
        df=df,
        stats_all=stats_all, stats_noshed=stats_noshed,
        corr_all=corr_all, corr_noshed=corr_noshed,
        ref_col="system_lambda_merit_order",
        ref_delta=ref_delta,
        shed_ts=shed_ts,
        n_clean=clean.shape[0],
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(md)
    print(f"wrote {args.out}  (n_all={df.shape[0]}  n_shed_clean={clean.shape[0]})")


if __name__ == "__main__":
    main()
