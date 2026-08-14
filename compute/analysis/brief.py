"""Pure SF projection primitives used by the query-backed analysis routes.

Three formulas carry the entire engine. The sign convention is `docs/SF.md`:
``SF < 0`` is import, and a constraint's contribution to a settlement point's
congestion price is ``-SF * mu``. Everything below derives from that one rule
and is exact — no approximation, no fitting.

    cell[c, sp]            = -SF[c, sp] * mu[c]                  ($/MWh)
    cong[sp]               = Σ_c cell[c, sp] = (-Sᵀ mu)[sp]      ($/MWh)
``mu`` is one hour's shadow-price vector (forecast μ̂ or realized DAM μ) indexed
by constraint key; ``SF`` is the constraints × settlement-points shift-factor
matrix. Both share the artifact's constraint vocabulary, so the pandas label
alignment below is exact rather than positional.
"""
from __future__ import annotations

import pandas as pd

def cell_contributions(SF: pd.DataFrame, mu: pd.Series) -> pd.DataFrame:
    """``-SF * mu`` per (constraint, settlement point), in $/MWh.

    Each row ``c`` is scaled by ``-mu[c]``; the result keeps ``SF``'s shape and
    labels. Rows align on ``mu.index``, so a constraint absent from ``mu`` yields
    NaN rather than a silent positional mismatch.
    """
    return SF.mul(-mu, axis=0)


def nodal_congestion(SF: pd.DataFrame, mu: pd.Series) -> pd.Series:
    """Forecast congestion price at each settlement point, ``cong = -Sᵀ mu``.

    Formed by the same per-cell contributions served by the node route.
    """
    return cell_contributions(SF, mu).sum(axis=0)
