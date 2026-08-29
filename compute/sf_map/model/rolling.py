"""Fit an implied-SF matrix for one refit window."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

from .fit import MIN_BINDING_HOURS, RIDGE_LAMBDA, STD_FLOOR, implied_shift_factors
from .grouping import aggregate_mu, constraint_linkage, cut_groups


@dataclass
class RefitWindow:
    """Inputs and fitted SF matrix for one refit window."""
    window_start: datetime
    window_end: datetime      # exclusive
    score_start: datetime
    score_end: datetime       # exclusive
    M_window: pd.DataFrame    # trailing shadow-price panel, RAW (constraints)
    C_window: pd.DataFrame    # trailing congestion panel used for the fit
    SF: pd.DataFrame          # (constraints × SPs), or (groups × SPs) if grouped

    # The panel handed to the ridge: `M_window` when ungrouped.
    # Diagnostics use this one — its
    # columns are what `SF`'s rows are keyed by. Identical object to `M_window`
    # when grouping is off, so ungrouped callers see no change.
    M_fit: pd.DataFrame
    # constraint_key → group_key for this window; None when ungrouped. Carries
    # the membership the persistence side (S2 commit 4) writes out.
    labels: pd.Series | None = None

def fit_refit_window(
    M_all: pd.DataFrame,
    C_all: pd.DataFrame,
    *,
    refit_start: pd.Timestamp,
    score_end: pd.Timestamp,
    window_days: int,
    lam: float = RIDGE_LAMBDA,
    min_hours: int = MIN_BINDING_HOURS,
    standardize: bool = True,
    std_floor: float = STD_FLOOR,
    rho_min: float | None = None,
) -> RefitWindow:
    """Fit one refit boundary from a panel containing its trailing history.

    Parameters
    ----------
    M_all, C_all
        Shadow-price and congestion panels. They may be a bounded chunk; only
        ``[score_end - window_days, score_end)`` participates in this fit.
        They are aligned on their union hour axis: missing μ is zero and
        missing congestion remains `NaN`.
    refit_start, score_end
        The associated score-period bounds. The fit window ends at
        ``score_end``.
    window_days
        Length of the trailing fit window.
    rho_min
        When set, collinear μ columns are grouped before the ridge solve.
    """

    idx = M_all.index.union(C_all.index).sort_values()
    M_all = M_all.reindex(idx).fillna(0.0)
    C_all = C_all.reindex(idx)

    window_end = score_end
    window_start = window_end - pd.Timedelta(days=window_days)
    win_mask = (M_all.index >= window_start) & (M_all.index < window_end)
    M_win = M_all.loc[win_mask]
    C_win = C_all.loc[win_mask]
    labels = None
    M_fit = M_win
    if M_win.empty:
        SF = pd.DataFrame(columns=C_all.columns)
    else:

        #
        # NB: rho_min collinear grouping branch does not execute in prod
        # see compute/grouping.py
        #
        if rho_min is not None:
            link = constraint_linkage(M_win)    # Z hierarchical cluster
            labels = cut_groups(link, rho_min)  # keys -> group
            M_fit = aggregate_mu(M_win, labels) # now grouped M with mu

        SF = implied_shift_factors(
            M_fit, C_win, lam=lam, min_hours=min_hours,
            standardize=standardize, std_floor=std_floor,
        )
    return RefitWindow(
        window_start=window_start.to_pydatetime(),
        window_end=window_end.to_pydatetime(),
        score_start=refit_start.to_pydatetime(),
        score_end=score_end.to_pydatetime(),
        M_window=M_win,
        C_window=C_win,
        SF=SF,
        M_fit=M_fit,
        labels=labels,
    )
