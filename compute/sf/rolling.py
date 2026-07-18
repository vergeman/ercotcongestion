"""Rolling-window refit.

Walk the hours forward one refit period at a time. At each refit boundary,
fit ``SF`` on the trailing ``window_days`` and hand the fitted window to
``on_refit_window`` — where the caller persists the SF matrix and its
per-window diagnostics.

``refit_days=1`` reproduces the prototype's every-day-refit cadence.
Default ``refit_days=7`` matches the weekly cadence in the doc.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import pandas as pd

from .fit import MIN_BINDING_HOURS, RIDGE_LAMBDA, STD_FLOOR, implied_shift_factors
from .grouping import aggregate_mu, constraint_linkage, cut_groups


@dataclass
class RefitWindow:
    """State handed to the per-refit callback so diagnostics can be computed
    without duplicating window-walking logic."""
    window_start: datetime
    window_end: datetime      # exclusive
    score_start: datetime
    score_end: datetime       # exclusive
    M_window: pd.DataFrame    # trailing shadow-price panel, RAW (constraints)
    C_window: pd.DataFrame    # trailing congestion panel used for the fit
    SF: pd.DataFrame          # (constraints × SPs), or (groups × SPs) if grouped
    # The panel actually handed to the ridge: `M_window` when ungrouped, its
    # group aggregate when `rho_min` is set. Diagnostics must use this one — its
    # columns are what `SF`'s rows are keyed by. Identical object to `M_window`
    # when grouping is off, so ungrouped callers see no change.
    M_fit: pd.DataFrame
    # constraint_key → group_key for this window; None when ungrouped. Carries
    # the membership the persistence side (S2 commit 4) writes out.
    labels: pd.Series | None = None


def _align(M: pd.DataFrame, C: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reindex M and C onto the union hour axis. Zero-mu hours are real
    (all constraints slack); NaN congestion hours are missing observations."""
    idx = M.index.union(C.index).sort_values()
    return M.reindex(idx).fillna(0.0), C.reindex(idx)


def rolling_sf(
    M_all: pd.DataFrame,
    C_all: pd.DataFrame,
    window_days: int = 60,
    refit_days: int = 7,
    lam: float = RIDGE_LAMBDA,
    min_hours: int = MIN_BINDING_HOURS,
    standardize: bool = True,
    std_floor: float = STD_FLOOR,
    rho_min: float | None = None,
    on_refit_window: Callable[[RefitWindow], None] | None = None,
    skip_window_starts: set[int] | None = None,
) -> None:
    """Refit every ``refit_days``, firing ``on_refit_window`` per boundary.

    Parameters
    ----------
    M_all, C_all
        Full-history panels (typically from ``panels.load_*``). Do NOT pre-align
        — this function reindexes onto the union hour axis.
    window_days
        Trailing window used for each fit.
    refit_days
        Days between successive fits.
    rho_min
        When set, collinear-group the window's μ columns (S2 / plan 0083) and
        fit on the group aggregate: co-binding constraints are not separately
        identifiable, so the group is the unit that can carry a signed claim.
        ``None`` (the default) is the ungrouped path, byte-identical to before.
    on_refit_window
        Callback receiving a ``RefitWindow`` after each fit — where the caller
        persists the SF matrix and per-window diagnostics without repeating the
        window-walking bookkeeping here.
    skip_window_starts
        Set of ``window_start`` ns-instants (``pd.Timestamp(ws).value``) to skip
        entirely — neither fit nor fire the callback. ``window_start`` fully
        determines a fit, so a boundary already persisted is byte-identical to
        recompute; the incremental map runner passes the already-persisted
        boundaries here so a weekly tick only fits the new ones.
    """
    M_all, C_all = _align(M_all, C_all)
    if M_all.empty:
        return

    all_days = pd.Index(M_all.index.normalize().unique()).sort_values()
    if len(all_days) == 0:
        return

    refit_dt = pd.Timedelta(days=refit_days)
    window_dt = pd.Timedelta(days=window_days)
    day_dt = pd.Timedelta(days=1)

    first_day = all_days[0]
    last_day = all_days[-1]

    # Refit boundaries: first_day, first_day + refit_days, ...
    refit_starts = pd.date_range(
        start=first_day, end=last_day, freq=refit_dt, inclusive="left",
    )
    if len(refit_starts) == 0:
        refit_starts = pd.DatetimeIndex([first_day])

    skip = skip_window_starts or set()
    for refit_start in refit_starts:
        score_end = min(refit_start + refit_dt, last_day + day_dt)
        # Trailing `window_days` ending at the score-period end. This reflects
        # the doc's retrospective framing ("60-day window, re-fit weekly") and,
        # at refit_days=1, matches the prototype's day-inclusive window.
        window_end = score_end
        window_start = window_end - window_dt

        # Already-persisted boundary: same window_start → byte-identical fit, so
        # skip the solve and the callback entirely (incremental map append).
        if window_start.value in skip:
            continue

        win_mask = (M_all.index >= window_start) & (M_all.index < window_end)
        M_win = M_all.loc[win_mask]
        C_win = C_all.loc[win_mask]
        labels = None
        M_fit = M_win
        if M_win.empty:
            SF = pd.DataFrame(columns=C_all.columns)
        else:
            if rho_min is not None:
                labels = cut_groups(constraint_linkage(M_win), rho_min)
                M_fit = aggregate_mu(M_win, labels)
            SF = implied_shift_factors(
                M_fit, C_win, lam=lam, min_hours=min_hours,
                standardize=standardize, std_floor=std_floor,
            )

        if on_refit_window is not None:
            on_refit_window(RefitWindow(
                window_start=window_start.to_pydatetime(),
                window_end=window_end.to_pydatetime(),
                score_start=refit_start.to_pydatetime(),
                score_end=score_end.to_pydatetime(),
                M_window=M_win,
                C_window=C_win,
                SF=SF,
                M_fit=M_fit,
                labels=labels,
            ))
