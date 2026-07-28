"""Pure analysis primitives for the daily brief engine.

Three formulas carry the entire engine. The sign convention is `docs/SF.md`:
``SF < 0`` is import, and a constraint's contribution to a settlement point's
congestion price is ``-SF * mu``. Everything below derives from that one rule
and is exact — no approximation, no fitting.

    cell[c, sp]            = -SF[c, sp] * mu[c]                  ($/MWh)
    cong[sp]               = Σ_c cell[c, sp] = (-Sᵀ mu)[sp]      ($/MWh)
    pair(sink, source)[c]  = mu[c] * (SF[source][c] - SF[sink][c])

The pair series sums *exactly* to ``cong[sink] - cong[source]`` (a positive
total means congestion is higher at the sink), so a per-constraint waterfall of
a node-to-node spread always reconciles to the spread itself.

``mu`` is one hour's shadow-price vector (forecast μ̂ or realized DAM μ) indexed
by constraint key; ``SF`` is the constraints × settlement-points shift-factor
matrix. Both share the artifact's constraint vocabulary, so the pandas label
alignment below is exact rather than positional.
"""
from __future__ import annotations

import pandas as pd

# The dead-cell threshold both June-30 walkthroughs used: below |SF| this small
# a cell carries no readable separation, only noise.
SF_MEANINGFUL = 0.05
# Screening cutoffs. Absolute $/MWh ranks first; these bound how much survives.
TOP_K_CONSTRAINTS = 10   # per hour
TOP_N_NODES = 5          # per side (import / export) per constraint


def cell_contributions(SF: pd.DataFrame, mu: pd.Series) -> pd.DataFrame:
    """``-SF * mu`` per (constraint, settlement point), in $/MWh.

    Each row ``c`` is scaled by ``-mu[c]``; the result keeps ``SF``'s shape and
    labels. Rows align on ``mu.index``, so a constraint absent from ``mu`` yields
    NaN rather than a silent positional mismatch.
    """
    return SF.mul(-mu, axis=0)


def nodal_congestion(SF: pd.DataFrame, mu: pd.Series) -> pd.Series:
    """Forecast congestion price at each settlement point, ``cong = -Sᵀ mu``.

    Equivalent to ``cell_contributions(SF, mu).sum(axis=0)`` but formed as one
    matrix-vector product; ``mu`` aligns to ``SF.index`` by label.
    """
    return -(SF.T @ mu.reindex(SF.index))


def pair_contributions(SF: pd.DataFrame, mu: pd.Series, sink: str, source: str) -> pd.Series:
    """Per-constraint drivers of the spread ``cong[sink] - cong[source]``.

    ``contribution[c] = mu[c] * (SF[source][c] - SF[sink][c])``. The series sums
    exactly to ``cong[sink] - cong[source]``; a positive entry pushes the sink's
    congestion above the source's. This is the waterfall behind a node-to-node
    separation story (F5).
    """
    return mu * (SF[source] - SF[sink])
