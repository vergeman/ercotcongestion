"""Rank a clustering sweep summary by composite quality score.

Reads `clustering_summary_<run_id>.json` (or `summary.json` under
`runs/<run_id>/clustering/`) produced by `compute.clustering.runner`,
computes a composite score per row, and prints the ranked table. Does NOT
auto-pick — the analyst makes the final call.

Composite (post-CM.6): a weighted sum of `sil_model` and `1 - sc_model`.
Higher is better: well-separated in feature space (`sil_model`) and
geographically coherent (`sc_model` is the intra/inter distance ratio —
smaller is more contiguous, so `1 - sc_model` is larger).

    score = alpha * sil_model + (1 - alpha) * (1 - sc_model)

`stab_model` is still displayed for context but no longer part of the
composite — ranking is a presentation-tier selector, not a validity
score (validity lives in CM.1–CM.3). ERCOT-side scores (`sil_ercot`,
`sc_ercot`) were retired in CM.4 and are no longer emitted or consumed.

NaNs in any composite component zero the score so rows without complete
diagnostics sink to the bottom rather than crashing the sort.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


COLUMNS = [
    "rank", "score", "ref", "algo", "K",
    "stab_model", "sil_model", "sc_model",
    "n_buses_model",
    "status",
]

DEFAULT_ALPHA = 0.5


def rank_summary(
    summary: dict,
    alpha: float = DEFAULT_ALPHA,
    top: int | None = None,
) -> pd.DataFrame:
    """Return the summary rows sorted descending by composite score."""
    df = pd.DataFrame(summary["rows"])
    if df.empty:
        return df

    sil = pd.to_numeric(df.get("sil_model"), errors="coerce")
    sc = pd.to_numeric(df.get("sc_model"), errors="coerce")
    score = alpha * sil + (1.0 - alpha) * (1.0 - sc)
    df["score"] = score.where(~score.isna(), 0.0)

    df = df.sort_values("score", ascending=False, kind="mergesort").reset_index(drop=True)
    df.insert(0, "rank", np.arange(1, len(df) + 1))
    if top is not None:
        df = df.head(top)
    cols = [c for c in COLUMNS if c in df.columns]
    return df[cols]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--summary", required=True, type=Path)
    p.add_argument("--top", type=int, default=20, help="rows to print; 0 = all")
    p.add_argument(
        "--alpha", type=float, default=DEFAULT_ALPHA,
        help="Composite weight on sil_model; (1-alpha) weights (1 - sc_model). "
             f"Default {DEFAULT_ALPHA}.",
    )
    args = p.parse_args(argv)

    if not (0.0 <= args.alpha <= 1.0):
        raise SystemExit(f"--alpha must be in [0, 1]; got {args.alpha}")

    with args.summary.open() as f:
        summary = json.load(f)

    top = None if args.top == 0 else args.top
    ranked = rank_summary(summary, alpha=args.alpha, top=top)
    if ranked.empty:
        print(f"no rows in {args.summary}")
        return 0

    with pd.option_context(
        "display.max_rows", None,
        "display.max_columns", None,
        "display.width", 200,
        "display.float_format", lambda v: f"{v:.4f}",
    ):
        print(ranked.to_string(index=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
