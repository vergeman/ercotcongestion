"""Persisted shift-factor map reads and forecast safety guards."""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from shared.settings import settings

log = logging.getLogger(__name__)

# Keep the established production map as the fallback, while allowing the
# deployed MAP_RUN_ID setting to select a different persisted map run.
MAP_RUN_ID = settings.map_run_id or "map-v1"
MAX_SF_AGE_DAYS = 14
MIN_SF_COVERAGE = 0.5


def resolve_sf_window(conn, run_id: str, *, as_of=None
                      ) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """Return the newest persisted map window causal to ``as_of``."""
    with conn.cursor() as cur:
        if as_of is None:
            cur.execute("SELECT window_start, window_end FROM sf_window_meta "
                        "WHERE run_id = %s ORDER BY window_start DESC LIMIT 1", (run_id,))
        else:
            cur.execute("SELECT window_start, window_end FROM sf_window_meta "
                        "WHERE run_id = %s AND window_end <= %s "
                        "ORDER BY window_start DESC LIMIT 1", (run_id, pd.Timestamp(as_of)))
        row = cur.fetchone()
    return None if row is None else (pd.Timestamp(row[0]), pd.Timestamp(row[1]))


def load_window_sf(conn, run_id: str, window_start, *,
                   fill_value: float | None = 0.0) -> pd.DataFrame:
    """Load one threshold-sparsified persisted map, filling omitted cells if set."""
    with conn.cursor() as cur:
        cur.execute("SELECT constraint_key, settlement_point, sf FROM implied_shift_factors "
                    "WHERE run_id = %s AND window_start = %s",
                    (run_id, pd.Timestamp(window_start)))
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["constraint_key", "settlement_point", "sf"])
    SF = df.pivot_table(index="constraint_key", columns="settlement_point", values="sf",
                        aggfunc="mean")
    if fill_value is not None:
        SF = SF.fillna(fill_value)
    SF.index.name = SF.columns.name = None
    return SF


def sf_mass_coverage(SF: pd.DataFrame, wp: pd.DataFrame) -> float:
    """Return the predicted binding mass represented by the persisted map."""
    e_mu = wp["p_bind"].to_numpy(float) * wp["mu_gbm"].to_numpy(float)
    total = float(np.nansum(np.abs(e_mu)))
    if total <= 0:
        return 1.0
    covered = wp["key"].isin(set(SF.index)).to_numpy()
    return float(np.nansum(np.abs(e_mu[covered])) / total)


def load_forecast_sf(conn, D, wp: pd.DataFrame, *, run_id: str = MAP_RUN_ID,
                     max_age_days: int = MAX_SF_AGE_DAYS,
                     min_coverage: float = MIN_SF_COVERAGE) -> pd.DataFrame:
    """Load a causal map and reject missing, stale, empty, or low-coverage maps."""
    D = pd.Timestamp(D)
    win = resolve_sf_window(conn, run_id, as_of=D)
    if win is None:
        raise RuntimeError(f"no persisted SF window for run_id={run_id!r} at/before {D.date()} — "
                           f"the weekly map ({run_id}) has not been built. Refusing to forecast "
                           "without geography (keep prior pointer).")
    window_start, window_end = win
    age = (D - window_end).days
    if age > max_age_days:
        raise RuntimeError(f"stale SF map for {D.date()}: the latest {run_id} window closes "
                           f"{window_end.date()} ({age}d old > {max_age_days}d floor). The weekly "
                           "refresh is behind — refusing to serve stale geography (keep pointer).")
    SF = load_window_sf(conn, run_id, window_start)
    if SF.empty:
        raise RuntimeError(f"empty SF matrix for {run_id} window {window_start.date()} — nothing "
                           f"to project {D.date()} through (keep prior pointer).")
    cov = sf_mass_coverage(SF, wp)
    if cov < min_coverage:
        raise RuntimeError(f"low SF coverage for {D.date()}: the {run_id} map locates "
                           f"{cov:.1%} of the day's predicted binding mass "
                           f"(< {min_coverage:.0%} floor). The map "
                           "universe and D's constraints have diverged — refusing (keep pointer).")
    log.info("SF from %s window %s (%dd old): %d constraints x %d SPs, coverage %.1f%%",
             run_id, window_start.date(), age, SF.shape[0], SF.shape[1], cov * 100)
    return SF
