"""Shared rig for the out-of-window SF experiments.

Every script here imports the production fit unmodified
(`compute.sf_map.model.fit.implied_shift_factors`) and the
production panels. The *only* departure from `rolling.rolling_sf` is the
window boundary:

    rolling.py:99-100 (production)   window_end = score_end
                                     -> the fit window CONTAINS the scored week

    honest_window() (here)           window_end = refit_start
                                     -> the fit window ends where scoring begins

That one line is the difference between the in-sample R² 0.986 the pipeline
reports and the 0.746 it is actually worth out-of-window.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import psycopg

from shared.settings import settings
from compute.inputs.dam import (
    load_congestion_panel,
    load_shadow_prices,
)

START = date(2025, 1, 1)
END = date(2026, 1, 1)
WINDOW_DAYS = 60
REFIT_DAYS = 7


def load_panels(start: date = START, end: date = END):
    """(M, C) aligned onto the union hour axis, as `rolling._align` does."""
    with psycopg.connect(settings.pg_dsn) as conn:
        M = load_shadow_prices(conn, start, end)
        C = load_congestion_panel(conn, start, end)
    idx = M.index.union(C.index).sort_values()
    return M.reindex(idx).fillna(0.0), C.reindex(idx)


def refit_starts(M: pd.DataFrame, window_days: int = WINDOW_DAYS,
                 refit_days: int = REFIT_DAYS) -> pd.DatetimeIndex:
    """Refit boundaries with a full trailing window behind each one."""
    days = pd.Index(M.index.normalize().unique()).sort_values()
    return pd.date_range(days[0] + pd.Timedelta(days=window_days), days[-1],
                         freq=pd.Timedelta(days=refit_days), inclusive="left")


def last_day(M: pd.DataFrame) -> pd.Timestamp:
    return pd.Index(M.index.normalize().unique()).sort_values()[-1]


def window(M: pd.DataFrame, start, end) -> pd.Index:
    return (M.index >= start) & (M.index < end)


def r2(y: np.ndarray, y_hat: np.ndarray) -> float:
    """Same definition as `diagnostics._r2`, so results are comparable."""
    m = np.isfinite(y) & np.isfinite(y_hat)
    y, y_hat = y[m], y_hat[m]
    if y.size < 2:
        return float("nan")
    ss_tot = float(((y - y.mean()) ** 2).sum())
    if ss_tot <= 0.0:
        return float("nan")
    return 1.0 - float(((y - y_hat) ** 2).sum()) / ss_tot


def predict(M_score: pd.DataFrame, SF: pd.DataFrame) -> np.ndarray:
    """C_hat = -M . SFᵀ over the constraints the fit actually kept."""
    cols = M_score.columns.intersection(SF.index)
    return -(M_score[cols].to_numpy(float) @ SF.loc[cols].to_numpy(float))


# --------------------------------------------------------------- mu forecasts
# The three mu sources compared in plan/version2-pivot-review.md sec 2.1.
# `oracle` is not a forecast -- it hands the model realized shadow prices and
# so measures the SF map alone. The other two are the pivot doc's own stated
# baselines (sec 3, "Baselines to beat and report").

def mu_oracle(M: pd.DataFrame, hours: pd.Index, cols: pd.Index) -> np.ndarray:
    return M.loc[hours, cols].to_numpy(float)


def mu_persistence(M: pd.DataFrame, hours: pd.Index, cols: pd.Index) -> np.ndarray:
    """Same hour-of-day, previous day."""
    return M.reindex(hours - pd.Timedelta(days=1))[cols].fillna(0.0).to_numpy(float)


def mu_climatology(M_fit: pd.DataFrame, hours: pd.Index, cols: pd.Index) -> np.ndarray:
    """P(bind | hour-of-day) x mean(mu | binding), both estimated on the fit
    window only. This is the pivot doc's "conditional historical mean"."""
    Mf = M_fit[cols]
    binding = Mf > 0
    mean_given_bind = Mf.where(binding).mean().fillna(0.0)
    p_bind = binding.groupby(Mf.index.hour).mean()
    return (p_bind.reindex(pd.Index(hours).hour).to_numpy(float)
            * mean_given_bind.to_numpy(float)[None, :])
