"""Per-hour metric: ``bp_ercot[sp, h] = max_{c binding at h} |SF[c, sp]|``.

NP4-191 publishes binding rows only, so the ``loading_c(h)`` factor from the
model-side metric is identically 1 and the max reduces to |SF|.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def binding_proximity(M: pd.DataFrame, SF: pd.DataFrame) -> pd.DataFrame:
    """Per-hour max ``|SF|`` over constraints active at that hour.

    Constraints present in ``M`` but absent from ``SF`` (rare-in-window,
    dropped by the fit) are skipped in the max — the trade-off documented
    in ``docs/implied_binding_proximity.md`` under "rare constraints".
    Hours with no binding constraint yield 0 for every SP, matching the
    model side's behavior on quiet hours.
    """
    common = M.columns.intersection(SF.index)
    if len(common) == 0:
        return pd.DataFrame(0.0, index=M.index, columns=SF.columns)

    A = (M[common].to_numpy() > 0)              # (hours × K)
    S = np.abs(SF.loc[common].to_numpy())       # (K × n_sp)
    # Broadcast-mask: rows of |SF| that are inactive at hour h are pushed to
    # -inf before the axis-max so they can never win. Any-binding hours then
    # come back as valid maxima; the fully-idle hours land at -inf and are
    # reset to 0 below.
    masked = np.where(A[:, :, None], S[None, :, :], -np.inf)
    bp = masked.max(axis=1)
    bp[~A.any(axis=1)] = 0.0
    return pd.DataFrame(bp, index=M.index, columns=SF.columns)
