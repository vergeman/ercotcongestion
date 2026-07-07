"""Ridge solve for implied shift factors.

DAM identity: ``congestion[h, sp] = − Σ_c SF[c, sp] · μ[h, c]``. Rearranged
into a linear system, ``C = −M · SFᵀ``; least-squares on the columns of ``C``
recovers ``SF`` up to the ridge regularization and the residual of any
constraint we omit from ``M`` (either because it was rare, or — see the doc's
Known Limitations — because the LMP-minus-λ input absorbs MCL).

The prototype used a fixed ``λ`` on raw μ, which shrinks constraints with
small typical shadow-price magnitudes disproportionately. Column-wise
standardization of ``M`` before the solve puts every constraint on a common
scale; coefficients are then rescaled back on the way out so the returned SF
matrix is in the natural ``$/MWh per MW`` units.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MIN_BINDING_HOURS = 10
RIDGE_LAMBDA = 1e-2


def implied_shift_factors(
    M: pd.DataFrame,
    C: pd.DataFrame,
    lam: float = RIDGE_LAMBDA,
    min_hours: int = MIN_BINDING_HOURS,
    standardize: bool = True,
) -> pd.DataFrame:
    """Ridge-solve for ``SF`` (constraints × SPs) on the given window.

    Parameters
    ----------
    M : DataFrame
        ``(hours × constraints)`` shadow-price panel from
        ``panels.load_shadow_prices``; zeros where not binding.
    C : DataFrame
        ``(hours × SPs)`` congestion panel from
        ``panels.load_congestion_panel``.
    lam : float
        Ridge regularization strength.
    min_hours : int
        Constraints binding in fewer than this many hours of the window are
        dropped — the coefficient is not identifiable and would just carry
        noise through the max in ``binding_proximity``.
    standardize : bool
        Divide each ``M`` column by its non-zero-hour standard deviation
        before solving, then rescale the recovered coefficients back. Keeps
        the ridge penalty from disproportionately shrinking small-μ
        constraints.
    """
    keep = (M > 0).sum() >= min_hours
    kept_cols = keep[keep].index
    Mk = M.loc[:, kept_cols]
    if Mk.shape[1] == 0:
        return pd.DataFrame(columns=C.columns)

    idx = M.index.intersection(C.index)
    X = Mk.loc[idx].to_numpy(dtype=float)
    Y = C.loc[idx].fillna(0.0).to_numpy(dtype=float)
    K = X.shape[1]

    if standardize:
        # Column-wise std over the fitted rows; guard the zero-column edge
        # case with a floor so we don't divide by zero on a degenerate window.
        scale = X.std(axis=0, ddof=0)
        scale = np.where(scale > 0, scale, 1.0)
        Xs = X / scale
    else:
        scale = np.ones(K)
        Xs = X

    beta = np.linalg.solve(Xs.T @ Xs + lam * np.eye(K), Xs.T @ Y)
    # Undo the scaling so SF is returned in $/MWh-per-MW units regardless of
    # `standardize`. Sign flip matches the identity C = −M · SFᵀ.
    beta = beta / scale[:, None]
    return pd.DataFrame(-beta, index=kept_cols, columns=C.columns)
