"""Rank a clustering sweep summary by composite quality score.

Reads `clustering_summary_<run_id>.json` produced by `compute.clustering.runner`,
computes a composite score per row, and prints the ranked table. Does NOT
auto-pick — the analyst makes the final call.

Score = `stab_model * sil_model * (1 - sc_model)`. Higher is better:
stable across time folds, well-separated in feature space, and
geographically coherent (`sc_model` is the intra/inter distance ratio —
smaller is more contiguous, so `1 - sc_model` is larger).

NaNs in any component zero the score so rows without complete diagnostics
sink to the bottom rather than crashing the sort.
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
    "n_buses_model", "n_polygons",
    "sil_ercot", "sc_ercot",
    "status",
]


def rank_summary(summary: dict, top: int | None = None) -> pd.DataFrame:
    """Return the summary rows sorted descending by composite score."""
    df = pd.DataFrame(summary["rows"])
    if df.empty:
        return df

    stab = pd.to_numeric(df.get("stab_model"), errors="coerce")
    sil = pd.to_numeric(df.get("sil_model"), errors="coerce")
    sc = pd.to_numeric(df.get("sc_model"), errors="coerce")
    score = stab * sil * (1.0 - sc)
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
    args = p.parse_args(argv)

    with args.summary.open() as f:
        summary = json.load(f)

    top = None if args.top == 0 else args.top
    ranked = rank_summary(summary, top=top)
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
