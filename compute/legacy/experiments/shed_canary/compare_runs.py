"""
Compare two snapshot_runner outputs (baseline vs post-shed-fix).

Usage:
    docker compose run --rm compute python /compute/experiments/shed_canary/compare_runs.py \
        --baseline /compute/runs/v1-120/congestion/model_results.json.gz \
        --candidate /compute/runs/v1-120-postfix/congestion/model_results.json.gz \
        --out /docs/shed_adapter_canary_full.md
"""
import argparse
import gzip
import json
import statistics
from pathlib import Path


def load(path: Path) -> list[dict]:
    with gzip.open(path, "rt") as f:
        return json.load(f)


def index(records: list[dict]) -> dict[tuple[str, str], dict]:
    return {(r["regime"], r["ts"]): r for r in records}


def pct(delta, base):
    if base is None or base == 0:
        return None
    return 100.0 * delta / abs(base)


def stat_row(label, deltas):
    finite = [d for d in deltas if d is not None]
    if not finite:
        return f"| {label} | (no data) |"
    return (
        f"| {label} | n={len(finite)} | "
        f"mean={statistics.mean(finite):+.2f} | "
        f"median={statistics.median(finite):+.2f} | "
        f"min={min(finite):+.2f} | "
        f"max={max(finite):+.2f} |"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", type=Path, required=True)
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    b_recs = load(args.baseline)
    c_recs = load(args.candidate)
    b_by = index(b_recs)
    c_by = index(c_recs)

    keys = sorted(set(b_by) & set(c_by))
    missing_c = sorted(set(b_by) - set(c_by))
    missing_b = sorted(set(c_by) - set(b_by))

    # Per-regime aggregation
    from collections import defaultdict
    delta_shed = defaultdict(list)
    delta_lmp_mean = defaultdict(list)
    delta_lmp_max = defaultdict(list)
    delta_lmp_min = defaultdict(list)
    shed_active_baseline = defaultdict(int)
    shed_active_candidate = defaultdict(int)
    pct_shed = defaultdict(list)

    # Rows for per-ts table (top by baseline shed)
    per_ts_rows = []
    for k in keys:
        regime, ts = k
        b, c = b_by[k], c_by[k]
        b_shed = b.get("load_shed_mw", 0.0)
        c_shed = c.get("load_shed_mw", 0.0)
        b_lmp = b.get("lmp_summary", {})
        c_lmp = c.get("lmp_summary", {})
        delta_shed[regime].append(c_shed - b_shed)
        pct_shed[regime].append(pct(c_shed - b_shed, b_shed))
        if b_shed > 1e-3: shed_active_baseline[regime] += 1
        if c_shed > 1e-3: shed_active_candidate[regime] += 1
        if b_lmp.get("mean") is not None and c_lmp.get("mean") is not None:
            delta_lmp_mean[regime].append(c_lmp["mean"] - b_lmp["mean"])
        if b_lmp.get("max") is not None and c_lmp.get("max") is not None:
            delta_lmp_max[regime].append(c_lmp["max"] - b_lmp["max"])
        if b_lmp.get("min") is not None and c_lmp.get("min") is not None:
            delta_lmp_min[regime].append(c_lmp["min"] - b_lmp["min"])
        per_ts_rows.append({
            "regime": regime, "ts": ts,
            "b_shed": b_shed, "c_shed": c_shed,
            "b_lmp_mean": b_lmp.get("mean"), "c_lmp_mean": c_lmp.get("mean"),
            "b_lmp_max": b_lmp.get("max"), "c_lmp_max": c_lmp.get("max"),
        })

    per_ts_rows.sort(key=lambda r: -r["b_shed"])

    lines = []
    lines.append("# Shed adapter fix — full v1-120 canary vs baseline\n")
    lines.append(f"Baseline: `{args.baseline}`  \nCandidate: `{args.candidate}`\n")
    lines.append(f"Records: baseline={len(b_recs)}, candidate={len(c_recs)}, "
                 f"matched={len(keys)}, only-baseline={len(missing_c)}, only-candidate={len(missing_b)}\n")

    lines.append("\n## Regime rollup — Δ = candidate − baseline\n")
    lines.append("### load_shed_mw\n")
    lines.append("| regime | stats |")
    lines.append("|---|---|")
    for regime in sorted(delta_shed):
        lines.append(stat_row(regime, delta_shed[regime]))
    lines.append("\n### lmp_mean\n")
    lines.append("| regime | stats |")
    lines.append("|---|---|")
    for regime in sorted(delta_lmp_mean):
        lines.append(stat_row(regime, delta_lmp_mean[regime]))
    lines.append("\n### lmp_max\n")
    lines.append("| regime | stats |")
    lines.append("|---|---|")
    for regime in sorted(delta_lmp_max):
        lines.append(stat_row(regime, delta_lmp_max[regime]))
    lines.append("\n### lmp_min\n")
    lines.append("| regime | stats |")
    lines.append("|---|---|")
    for regime in sorted(delta_lmp_min):
        lines.append(stat_row(regime, delta_lmp_min[regime]))

    lines.append("\n### shed-active count (load_shed_mw > 0)\n")
    lines.append("| regime | baseline | candidate |")
    lines.append("|---|---|---|")
    for regime in sorted(set(shed_active_baseline) | set(shed_active_candidate)):
        lines.append(f"| {regime} | {shed_active_baseline[regime]} | {shed_active_candidate[regime]} |")

    lines.append("\n## Top 20 timestamps by baseline shed\n")
    lines.append("| regime | ts | baseline shed | candidate shed | Δshed | baseline lmp_mean | candidate lmp_mean | baseline lmp_max | candidate lmp_max |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for r in per_ts_rows[:20]:
        def f(v, fmt=".1f"):
            return "--" if v is None else f"{v:{fmt}}"
        d = r["c_shed"] - r["b_shed"]
        lines.append(
            f"| {r['regime']} | {r['ts']} | {f(r['b_shed'])} | {f(r['c_shed'])} | "
            f"{d:+.1f} | {f(r['b_lmp_mean'], '.2f')} | {f(r['c_lmp_mean'], '.2f')} | "
            f"{f(r['b_lmp_max'], '.2f')} | {f(r['c_lmp_max'], '.2f')} |"
        )

    if missing_c or missing_b:
        lines.append("\n## Mismatches\n")
        if missing_c:
            lines.append("Only in baseline:\n")
            for k in missing_c[:20]:
                lines.append(f"* {k[0]}  {k[1]}")
        if missing_b:
            lines.append("Only in candidate:\n")
            for k in missing_b[:20]:
                lines.append(f"* {k[0]}  {k[1]}")

    args.out.write_text("\n".join(lines) + "\n")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
