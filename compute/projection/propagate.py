"""Deterministic SF projection: ``point = −(E_mu · SF)``.

``propagate_window`` is the main function that turns a window's expected μ into
the nodal point forecast. Imported by forecast publication and evaluation.

This houses the actual forecasts:
  1. E_mu = p_bind * mu_gbm
  2. point = -(E_mu  @ SF)

"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from compute.sf_map.config import MIN_HOURS, RIDGE_LAMBDA as LAM, WINDOW_DAYS
from compute.sf_map.model.fit import implied_shift_factors
from compute.metrics import screening_metrics
from compute.projection.codecs import NodalPanel

STD_FLOOR = 100.0

log = logging.getLogger("compute.projection.propagate")


def _sf_for_window(s: pd.Timestamp, M: pd.DataFrame, C: pd.DataFrame,
                   sf: pd.DataFrame | None) -> pd.DataFrame:
    """Return an injected map, or fit one from the preceding rolling window."""
    if sf is not None:
        return sf
    lo = s - pd.Timedelta(days=WINDOW_DAYS)
    M_fit = M.loc[(M.index >= lo) & (M.index < s)]
    if M_fit.empty:
        return pd.DataFrame()
    C_fit = C.loc[(C.index >= lo) & (C.index < s)]
    return implied_shift_factors(M_fit, C_fit, lam=LAM, min_hours=MIN_HOURS,
                                 standardize=True, std_floor=STD_FLOOR)


def _aligned_score_inputs(s: pd.Timestamp, end: pd.Timestamp, M: pd.DataFrame,
                          C: pd.DataFrame, SF: pd.DataFrame,
                          forward_hours: pd.DatetimeIndex | None,
                          ) -> tuple[pd.DataFrame, pd.DatetimeIndex, pd.DataFrame]:
    """Select scoring hours and remove nodes unavailable in realized congestion."""
    M_score = M.loc[(M.index >= s) & (M.index < end)]
    if forward_hours is not None:
        return M_score, forward_hours, SF

    C_score = C.loc[(C.index >= s) & (C.index < end)]
    absent = SF.columns.difference(C_score.columns)
    if len(absent):
        log.info("week %s: dropping %d SP(s) absent from congestion panel "
                 "(retired/renamed, e.g. %s)", s.date(), len(absent),
                 ", ".join(map(str, absent[:3])))
        SF = SF.loc[:, SF.columns.intersection(C_score.columns)]

    # M, mutual hours, SF
    return M_score, M_score.index.intersection(C_score.index), SF


def _sf_coverage(M_score: pd.DataFrame, SF: pd.DataFrame) -> float:
    """Return the share of score-window shadow-price mass represented by SF."""
    mass_all = float(M_score.abs().to_numpy(float).sum())
    if mass_all <= 0:
        return np.nan
    covered = M_score.columns.intersection(SF.index)
    return float(M_score[covered].abs().to_numpy(float).sum() / mass_all)


def _expected_mu(wp: pd.DataFrame, SF: pd.DataFrame,
                 hours: pd.DatetimeIndex) -> pd.DataFrame:
    """Build hour × constraint expected μ, aligned to the SF matrix."""
    wp = wp[wp["key"].isin(SF.index)]

    def wide(column: str) -> pd.DataFrame:
        return (wp.pivot_table(index="interval_ts", columns="key", values=column,
                               aggfunc="mean")
                .reindex(index=hours, columns=SF.index).fillna(0.0))

    return wide("p_bind") * wide("mu_gbm")


def propagate_window(
    s: pd.Timestamp, end: pd.Timestamp,
    M: pd.DataFrame, C: pd.DataFrame, wp: pd.DataFrame,
    *, want_panel: bool = False, want_sf_mu: bool = False,
    forward_hours: pd.DatetimeIndex | None = None,
    sf: pd.DataFrame | None = None,
) -> tuple[dict | None, NodalPanel | None, pd.DataFrame | None, pd.DataFrame | None]:
    """One window, shared by the backtest and `forecast_day`.

    Score the projection over ``[s, end)``. The SF map comes from one of two
    places: fit on ``[s−WINDOW_DAYS, s)`` here (``sf=None``, the
    historic/self-contained path), or the persisted weekly map passed in via
    ``sf``

    Forward mode: the scored hours are the caller's (daily_forecast.py)
    delivery-day calendar (D's 24 intervals rather than ``M_score ∩ C_score``;
    it does not read future realized congestion and returns no metrics row.
    Empty fit/map/hour inputs return ``(None, None, None, None)``.

    """
    forward = forward_hours is not None
    SF = _sf_for_window(s, M, C, sf)    # date-aligned SF
    if SF.empty:
        return None, None, None, None

    M_score, hours, SF = _aligned_score_inputs(s, end, M, C, SF, forward_hours)  # M, SF - aligned w/ C
    if SF.empty or not len(hours):
        return None, None, None, None

    sf_coverage = _sf_coverage(M_score, SF)  # single number threshold: mu (M in SF) / total M
    E_mu = _expected_mu(wp, SF, hours)       # calc p_bind * mu_gbm
    point = -(E_mu.to_numpy(np.float32) @ SF.to_numpy(np.float32))
    panel = NodalPanel(ts=hours.to_numpy(),
                       settlement_points=SF.columns.to_numpy(),
                       point=point.astype(np.float32),
                       sf_r2=None) if want_panel else None

    row = None
    if not forward:
        Y = C.loc[hours, SF.columns].to_numpy(np.float32)
        row = {"week": s, "n_hours": len(hours), "n_nodes": SF.shape[1],
               "sf_coverage": sf_coverage, **screening_metrics(Y, point)}
    return row, panel, (SF if want_sf_mu else None), (E_mu if want_sf_mu else None)
