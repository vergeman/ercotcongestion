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
TOP_N_HOTSPOTS = 10      # highest-|congestion| settlement points per hour
# Day roll-up: how many hours a constraint/node must recur in to make the
# watchlist — a quarter of the delivery day.
WATCHLIST_MIN_HOURS = 6


def cell_contributions(SF: pd.DataFrame, mu: pd.Series) -> pd.DataFrame:
    """``-SF * mu`` per (constraint, settlement point), in $/MWh.

    Each row ``c`` is scaled by ``-mu[c]``; the result keeps ``SF``'s shape and
    labels. Rows align on ``mu.index``, so a constraint absent from ``mu`` yields
    NaN rather than a silent positional mismatch.
    """
    return SF.mul(-mu, axis=0)


def nodal_congestion(SF: pd.DataFrame, mu: pd.Series) -> pd.Series:
    """Forecast congestion price at each settlement point, ``cong = -Sᵀ mu``.

    Formed by the same per-cell contributions exposed in a driver waterfall.
    Besides keeping the sign convention in one place, this gives pair terms and
    endpoint totals a deterministic float64 reduction path when artifacts store
    their SF values as float32.
    """
    return cell_contributions(SF, mu).sum(axis=0)


def pair_contributions(SF: pd.DataFrame, mu: pd.Series, sink: str, source: str) -> pd.Series:
    """Per-constraint drivers of the spread ``cong[sink] - cong[source]``.

    ``contribution[c] = mu[c] * (SF[source][c] - SF[sink][c])``. The series sums
    exactly to ``cong[sink] - cong[source]``; a positive entry pushes the sink's
    congestion above the source's. This is the waterfall behind a node-to-node
    separation story (F5).
    """
    # Subtract the same per-node cells that form ``nodal_congestion`` instead
    # of first subtracting two float32 SF columns. They are algebraically
    # identical, but this order avoids a measurable reduction-order residual
    # when a large full artifact is summed.
    cells = cell_contributions(SF, mu)
    return cells[sink] - cells[source]


def congestion_bias(forecast_cong: pd.Series, realized_cong: pd.Series,
                    *, signed: bool = False) -> float:
    """Mean forecast-minus-realized congestion bias, on ``|congestion|`` by default.

    Node congestion is signed by shift factor, so signed errors let an
    over-called import net against an under-called export into a spurious
    "balanced" bias while both are wrong (the ``0003`` netting trap). Scoring
    the magnitude matches the unsigned constraint half; ``signed=True`` exists
    only so a test can pin the difference. Series align on shared SPs first.
    """
    forecast_cong, realized_cong = forecast_cong.align(realized_cong, join="inner")
    if not signed:
        forecast_cong, realized_cong = forecast_cong.abs(), realized_cong.abs()
    return float((forecast_cong - realized_cong).mean())
