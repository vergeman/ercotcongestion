"""Deterministic SF projection: ``point = −(E_mu · SF)``.

The serving and historical-backfill paths share this point-only projection. It
owns no database writes; runners in ``compute.jobs`` handle persistence.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from compute.sf_map.config import MIN_HOURS, RIDGE_LAMBDA as LAM, WINDOW_DAYS
from compute.sf_map.model.fit import implied_shift_factors
from compute.metrics import score_matrix
from compute.projection.codecs import NodalPanel

STD_FLOOR = 100.0

log = logging.getLogger("compute.projection.propagate")


def propagate_window(
    s: pd.Timestamp, end: pd.Timestamp,
    M: pd.DataFrame, C: pd.DataFrame, wp: pd.DataFrame,
    *, want_panel: bool = False, want_sf_mu: bool = False,
    forward_hours: pd.DatetimeIndex | None = None,
    sf: pd.DataFrame | None = None,
) -> tuple[dict | None, NodalPanel | None, pd.DataFrame | None, pd.DataFrame | None]:
    """One window, shared by the backtest and `forecast_day`.

    Score the deterministic projection over ``[s, end)``. The SF map comes from
    one of two places: fit on ``[s−WINDOW_DAYS, s)`` here (``sf=None``, the
    historic/self-contained path), or the persisted weekly map passed in via
    ``sf``

    Returns ``(row, None, None, None)`` normally; with ``want_panel`` also the
    `NodalPanel` containing the point forecast; with ``want_sf_mu`` also the
    ``SF`` (K×N) actually used and ``E_mu`` (H×K on ``SF.index``) for the SF+μ
    artifact (§4a). ``(None, None, None, None)`` on any skip (empty fit window,
    empty SF, no scored hours) — the caller's `continue`.

    **Forward mode** (`forward_hours` given — `forecast_day` for a delivery day
    D with no realized congestion yet, §3.2): the scored hours are the caller's
    delivery-day calendar (D's 24 intervals) rather than ``M_score ∩ C_score``,
    no realized ``Y`` is read (``C`` is never indexed on the score side, so a
    ``C`` that is empty/absent for D cannot crash the panel), and ``row`` is
    ``None`` (no metrics without an outcome).

    """
    forward = forward_hours is not None
    if sf is None:
        lo, hi = s - pd.Timedelta(days=WINDOW_DAYS), s
        M_fit = M.loc[(M.index >= lo) & (M.index < hi)]
        C_fit = C.loc[(C.index >= lo) & (C.index < hi)]
        if M_fit.empty:
            return None, None, None, None
        SF = implied_shift_factors(M_fit, C_fit, lam=LAM, min_hours=MIN_HOURS,
                                   standardize=True, std_floor=STD_FLOOR)
    else:
        SF = sf                             # persisted weekly map (already guarded)
    if SF.empty:
        return None, None, None, None

    M_score = M.loc[(M.index >= s) & (M.index < end)]
    if forward:
        hours = forward_hours
    else:
        C_score = C.loc[(C.index >= s) & (C.index < end)]
        hours = M_score.index.intersection(C_score.index)
        # The persisted SF was fit on a 240-day window that can include settlement
        # points retired/renamed before this scored week — they are simply absent
        # from the congestion panel here. Drop them: a node the SP data no longer
        # carries can be neither realized (graded) nor honestly projected. (Forward
        # mode never indexes C on the score side, so it keeps the full map.)
        absent = SF.columns.difference(C_score.columns)
        if len(absent):
            log.info("week %s: dropping %d SP(s) absent from congestion panel "
                     "(retired/renamed, e.g. %s)", s.date(), len(absent),
                     ", ".join(map(str, absent[:3])))
            SF = SF.loc[:, SF.columns.intersection(C_score.columns)]
            if SF.empty:
                return None, None, None, None
    if not len(hours):
        return None, None, None, None

    wp = wp[wp["key"].isin(SF.index)]  # NB: used in wide()

    # ratio of intersection mu over all mu
    # cov_cols: mu of constraints in both M and SF
    # mass_all: all mu
    # sf_coverage = cov_cols / mass_all

    mass_all = float(M_score.abs().to_numpy(float).sum())
    cov_cols = M_score.columns.intersection(SF.index)
    sf_coverage = (float(M_score[cov_cols].abs().to_numpy(float).sum())
                   / mass_all if mass_all > 0 else np.nan)

    def wide(column: str) -> pd.DataFrame:
        return (wp.pivot_table(index="interval_ts", columns="key", values=column,
                               aggfunc="mean")
                .reindex(index=hours, columns=SF.index).fillna(0.0))

    # P(bind): hour x constraint, mu_gbm: hr x constraint
    # E[μ]: P(bind) x mu_gbm = hours x constraints
    # SF: hour x settlement point
    #
    # point: = E[μ] @ SF  -> (hr x constraint) @ (constraint x settlement point)
    # hour x settlement point
    #
    # E[μ] = P(bind) · E[μ | bind], projected directly through the SF map.

    E_mu = wide("p_bind") * wide("mu_gbm")
    point = -(E_mu.to_numpy(np.float32) @ SF.to_numpy(np.float32))
    panel = NodalPanel(ts=hours.to_numpy(),
                       settlement_points=SF.columns.to_numpy(),
                       point=point.astype(np.float32),
                       sf_r2=None) if want_panel else None

    row = None
    if not forward:
        # hours ⊆ C_score.index ⊆ C.index, so this selects the same rows in the
        # same order as the pre-forward `C_score.loc[hours]`, byte-identical.
        Y = C.loc[hours, SF.columns].to_numpy(np.float32)
        row = {"week": s, "n_hours": len(hours), "n_nodes": SF.shape[1],
               "sf_coverage": sf_coverage, **score_matrix(Y, point)}
    return row, panel, (SF if want_sf_mu else None), (E_mu if want_sf_mu else None)
