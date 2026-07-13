"""
Compare correlation_map outcomes under multiple (model_ref, ercot_ref)
pairs, against the same run-id / rectangle.

For each pair configured in the input JSON we:
  * Load the model/ERCOT congestion matrices via correlation_map.load_matrices.
  * Prefilter low-variance rows the same way correlation_map does.
  * Compute the SP -> best-bus correlation array (Pearson over shared hours).
  * Emit a headline row: median_corr, p90, p99, pct>0.5, distinct_winners,
    top-3 winner share.
  * Opportunistically merge in scorecard metrics (zone_rank_spearman_per_hour,
    mean_corr, mean_sign_agreement) from any existing
    `runs/<run_id>/mapping/scorecard_<run_id>_<model_ref>_*_k*.json`
    file for the same model-side ref. If none exists, those columns are NaN.

Writes `runs/<run_id>/compare/compare.csv` and `.md` — rows = pairs,
columns = the metrics above, in the plan's column order.

Usage:
    python -m compute.legacy.mapping.compare_refs --run-id v1-annual-zonelocal \\
        [--pairs mapping/pairs/default.json] \\
        [--var-threshold 1.0] [--topk 5]
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import numpy as np

from compute.legacy.mapping.correlation_map import (
    RUNS_ROOT,
    correlate,
    load_matrices,
    prefilter_low_variance,
    select_best_and_topk,
)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_PAIRS = BASE_DIR / "pairs" / "default.json"

METRIC_ORDER = (
    "zone_rank_spearman_per_hour",
    "mean_corr",
    "sign_agreement",
    "median_corr",
    "p90",
    "p99",
    "pct_gt_0_5",
    "distinct_winners",
    "top3_share",
)


def _compare_dir(run_id: str) -> Path:
    return RUNS_ROOT / run_id / "compare"


def _mapping_dir(run_id: str) -> Path:
    return RUNS_ROOT / run_id / "mapping"


def _load_pairs(path: Path) -> list[dict[str, str]]:
    with open(path) as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        raise SystemExit(f"pairs file {path} must be a JSON list")
    for entry in raw:
        if not isinstance(entry, dict):
            raise SystemExit(f"pairs entry must be an object: {entry!r}")
        for k in ("name", "model_ref", "ercot_ref"):
            if k not in entry:
                raise SystemExit(f"pairs entry missing {k!r}: {entry!r}")
    return raw


def _scorecard_metrics(run_id: str, model_ref: str) -> dict[str, float | None]:
    """Best-effort read of scorecard headline for `model_ref`.

    Scorecard files are named
    `scorecard_<run_id>_<ref>_<algo>_k<K>.json`. We pick the newest one
    matching `<ref> == model_ref`. If none exists, returns None values —
    scorecard depends on a per-ref clustering artifact and isn't run
    automatically by the compare harness.
    """
    d = _mapping_dir(run_id)
    if not d.exists():
        return {"zone_rank_spearman_per_hour": None, "mean_corr": None, "sign_agreement": None}
    candidates = sorted(
        d.glob(f"scorecard_{run_id}_{model_ref}_*_k*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return {"zone_rank_spearman_per_hour": None, "mean_corr": None, "sign_agreement": None}
    with open(candidates[0]) as f:
        raw = json.load(f)
    headline = raw.get("headline") or raw
    return {
        "zone_rank_spearman_per_hour": headline.get("zone_rank_spearman_per_hour"),
        "mean_corr": headline.get("mean_corr"),
        "sign_agreement": (
            headline.get("mean_sign_agreement")
            or headline.get("sign_agreement")
        ),
    }


def _headline_from_best_corr(
    best_corr: np.ndarray,
    best_bus: np.ndarray,
) -> dict[str, float | int]:
    finite = best_corr[np.isfinite(best_corr)]
    n_sp = int(best_corr.size)
    if finite.size == 0:
        return {
            "median_corr": float("nan"),
            "p90": float("nan"),
            "p99": float("nan"),
            "pct_gt_0_5": float("nan"),
            "distinct_winners": 0,
            "top3_share": float("nan"),
        }
    # Winner-concentration metrics use best_bus (may include NaN sentinels
    # from all-NaN rows — filter to finite-corr rows so a bus that "wins"
    # no valid SP doesn't get counted).
    winners = best_bus[np.isfinite(best_corr)]
    unique, counts = np.unique(winners, return_counts=True)
    order = np.argsort(-counts)
    top3 = int(counts[order[:3]].sum()) if counts.size else 0
    return {
        "median_corr": float(np.median(finite)),
        "p90": float(np.quantile(finite, 0.90)),
        "p99": float(np.quantile(finite, 0.99)),
        "pct_gt_0_5": float((finite > 0.5).mean()),
        "distinct_winners": int(unique.size),
        "top3_share": float(top3 / n_sp) if n_sp else float("nan"),
    }


def evaluate_pair(
    run_id: str,
    model_ref: str,
    ercot_ref: str,
    var_threshold: float,
    topk: int,
) -> dict[str, Any]:
    """One row of the compare table.

    Mirrors the pipeline of correlation_map.main: load -> prefilter ->
    correlate -> best/topk -> headline. Then merges in scorecard headline
    for the same model_ref if a summary JSON exists.
    """
    model_C, ercot_C, bus_ids, sp_ids, hours = load_matrices(
        run_id, model_ref=model_ref, ercot_ref=ercot_ref,
    )
    model_C, bus_ids, _ = prefilter_low_variance(model_C, bus_ids, var_threshold)
    ercot_C, sp_ids, _ = prefilter_low_variance(ercot_C, sp_ids, var_threshold)
    R = correlate(model_C, ercot_C)
    best_bus, best_corr, _ = select_best_and_topk(R, bus_ids, topk)

    row: dict[str, Any] = {
        "model_ref": model_ref,
        "ercot_ref": ercot_ref,
        "n_bus": int(bus_ids.shape[0]),
        "n_sp": int(sp_ids.shape[0]),
        "n_hours": int(hours.shape[0]),
    }
    row.update(_headline_from_best_corr(best_corr, best_bus))
    row.update(_scorecard_metrics(run_id, model_ref))
    return row


def _fmt(v: Any, spec: str = ".3f") -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        if np.isnan(v):
            return "—"
        return format(v, spec)
    return str(v)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    fieldnames = ["name", "model_ref", "ercot_ref", "n_bus", "n_sp", "n_hours"] + list(METRIC_ORDER)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fieldnames})


def _write_md(path: Path, rows: list[dict[str, Any]], run_id: str) -> None:
    header_cols = [
        "pair",
        "zone_rank_spearman_per_hour",
        "mean_corr",
        "sign_agree",
        "median",
        "p90",
        "p99",
        "pct>0.5",
        "distinct_winners",
        "top3_share",
    ]
    lines: list[str] = [
        f"# Compare refs — {run_id}",
        "",
        "One matrix, many `(model_ref, ercot_ref)` pairs. Metrics on the",
        "left come from the per-ref scorecard summary if present (else —);",
        "metrics on the right are computed by this harness.",
        "",
        "| " + " | ".join(header_cols) + " |",
        "|" + "|".join("---" for _ in header_cols) + "|",
    ]
    for r in rows:
        lines.append(
            "| " + " | ".join([
                r.get("name", ""),
                _fmt(r.get("zone_rank_spearman_per_hour")),
                _fmt(r.get("mean_corr")),
                _fmt(r.get("sign_agreement")),
                _fmt(r.get("median_corr")),
                _fmt(r.get("p90")),
                _fmt(r.get("p99")),
                _fmt(100.0 * r["pct_gt_0_5"], ".1f") + "%"
                    if r.get("pct_gt_0_5") is not None and not (
                        isinstance(r["pct_gt_0_5"], float) and np.isnan(r["pct_gt_0_5"])
                    ) else "—",
                _fmt(r.get("distinct_winners"), "d") if r.get("distinct_winners") is not None else "—",
                _fmt(100.0 * r["top3_share"], ".1f") + "%"
                    if r.get("top3_share") is not None and not (
                        isinstance(r["top3_share"], float) and np.isnan(r["top3_share"])
                    ) else "—",
            ]) + " |"
        )
    lines.append("")
    path.write_text("\n".join(lines))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", required=True,
                    help="Run identifier under compute/runs/.")
    ap.add_argument("--pairs", type=Path, default=DEFAULT_PAIRS,
                    help=f"JSON list of {{name, model_ref, ercot_ref}} "
                         f"entries (default: {DEFAULT_PAIRS.name}).")
    ap.add_argument("--var-threshold", type=float, default=1.0,
                    help="Drop rows with std < threshold ($/MWh, default 1.0).")
    ap.add_argument("--topk", type=int, default=5,
                    help="Top-k for winner selection (default 5). Not "
                         "reflected in the summary; kept for parity with "
                         "correlation_map.")
    args = ap.parse_args(argv)

    pairs = _load_pairs(args.pairs)
    out_dir = _compare_dir(args.run_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    for entry in pairs:
        name = entry["name"]
        model_ref = entry["model_ref"]
        ercot_ref = entry["ercot_ref"]
        print(f"[{name}] {model_ref} × {ercot_ref}")
        try:
            row = evaluate_pair(
                args.run_id, model_ref, ercot_ref,
                args.var_threshold, args.topk,
            )
        except SystemExit as e:
            print(f"  skipped: {e}")
            row = {"model_ref": model_ref, "ercot_ref": ercot_ref}
        row["name"] = name
        rows.append(row)

    csv_path = out_dir / "compare.csv"
    md_path = out_dir / "compare.md"
    _write_csv(csv_path, rows)
    _write_md(md_path, rows, args.run_id)
    print(f"wrote {csv_path}")
    print(f"wrote {md_path}")


if __name__ == "__main__":
    main()
