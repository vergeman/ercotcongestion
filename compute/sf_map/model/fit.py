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

from compute.sf_map.config import MIN_HOURS as MIN_BINDING_HOURS, RIDGE_LAMBDA

# The admission floor (`min_hours`) and ridge (`λ`) are the adopted operating
# point (`compute.sf_map.config`) — single-sourced so the μ forecast and the SF map
# cannot drift. The sweep in `compute.experiments.sf.sweep` (see README "Trial findings")
# originally tuned `min=25 / λ=0.1 / std_floor=100` on a 60-day / weekly-refit
# schedule; the honest OOS re-sweep (plan/0082 S1.5) then selected λ=1.0 on a
# 240-day window — better OOS R² (0.708→0.734), coverage (0.810→0.861), and
# refit-horizon drift — and that is what `config` now carries.
# Constraints whose in-window shadow-price std is below this get treated
# like zero-variance columns during standardization. Without the floor, a
# near-quiet column's `1/scale` rescale inflates its coefficient into the
# physically-impossible range and the ±1 cap has to catch it.
STD_FLOOR = 100.0
# SFs are unitless in [-1, 1]. Anything larger is a numerical artifact of the
# ridge solve on a poorly-conditioned column; clip and count.
SF_ABS_CAP = 1.0


def implied_shift_factors(
    M: pd.DataFrame,
    C: pd.DataFrame,
    lam: float = RIDGE_LAMBDA,
    min_hours: int = MIN_BINDING_HOURS,
    standardize: bool = True,
    std_floor: float = STD_FLOOR,
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
        dropped.
    standardize : bool
        Divide each ``M`` column by its non-zero-hour standard deviation
        before solving, then rescale the recovered coefficients back. Keeps
        the ridge penalty from disproportionately shrinking small-μ
        constraints.
    std_floor : float
        Lower bound on the per-column std used for standardization; larger
        values suppress inflation of coefficients on low-variance columns
        at the cost of over-shrinking their signal. Ignored when
        ``standardize=False``.
    """
    # toggle all cells for > 0, then sum column-wise for count
    # test for min_hours
    keep = (M > 0).sum() >= min_hours
    kept_cols = keep[keep].index

    # check for empty cols (shape[1])
    Mk = M.loc[:, kept_cols]
    if Mk.shape[1] == 0:
        out = pd.DataFrame(columns=C.columns)
        out.attrs["n_clipped"] = 0
        return out

    # filter M & C for same hourly row
    idx = M.index.intersection(C.index)
    X = Mk.loc[idx].to_numpy(dtype=float)              # (hours, constraints)
    Y = C.loc[idx].fillna(0.0).to_numpy(dtype=float)   # (hours, nodes)
    K = X.shape[1]                                     # num cols

    if standardize:
        # Column-wise std over the fitted rows, floored so both zero-variance
        # and low-variance columns get the same treatment. Without the floor,
        # a near-quiet column's `1/scale` rescale inflates its coefficient
        # into the physically-impossible range.
        #
        # X.std takes range of each columns shadow prices, then computes
        # columnwise (constraint) shadow price ranges over time (rows)
        #
        # X / scale normalizes values ~ 1
        scale = np.maximum(X.std(axis=0, ddof=0), std_floor)
        Xs = X / scale
    else:
        scale = np.ones(K)
        Xs = X

    #
    # ridge regression
    #
    # Ax=B
    # x = np.linalg.solve(A, B)
    # sf = np.linalg.solve(M, C)
    #
    # A: Xs.T @ Xs + lam * np.eye(K)
    #
    #   Xᵀ * X      (NB: X is M hours/constraints)
    #
    #   ridge penalty: lam * np.eye
    #                  lambda * I (identity matrix)
    #
    # B: Xs.T @ Y
    #
    #    Xᵀ * Y     (NB: Y is C hours/nodes)
    #
    #
    # 1. C = −M · SFᵀ
    # 2. Y =  X · B         (B = -SFᵀ)
    #
    # 3. r = Y - XB        (r residual)
    # 4. min ||r||^2
    #    Xᵀ r = 0          (least squares) - r is perpendicular to X
    # 5. Xᵀ(Y − XB) = 0    (sub no. 3)
    #
    # 6. XᵀY − XᵀX B = 0
    # 7. XᵀX B  = XᵀY
    # 8. (XᵀX + λI)β = XᵀY  (add ridge penalty)
    # 9. A   x  = B
    #    x = solve(A, B)
    #
    # x is the -sf. [-1, 1] (beta / out)

    beta = np.linalg.solve(Xs.T @ Xs + lam * np.eye(K), Xs.T @ Y)
    # Undo the scaling so SF is returned regardless of `standardize`.
    # we scale so lambda can equally affect all cells e.g. 500k vs 50
    # lambda is order of magnitude difference
    #
    # Sign flip matches the identity C = −M · SFᵀ.
    #
    beta = beta / scale[:, None]
    sf = -beta
    n_clipped = int(np.sum(np.abs(sf) > SF_ABS_CAP))
    sf = np.clip(sf, -SF_ABS_CAP, SF_ABS_CAP)
    out = pd.DataFrame(sf, index=kept_cols, columns=C.columns)
    out.attrs["n_clipped"] = n_clipped
    return out
