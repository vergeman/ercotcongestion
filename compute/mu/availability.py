"""Availability rules for the μ feature panel.

The prediction is made at DAM close: 10:00 CT on D-1.  Every feature must be
answerable from that vantage point.  Forecasts and outages use their newest
``posted_datetime <= DAM close`` vintage; day D's shadow prices are never
available, while all of D-1 is public and legal history.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from compute.time import ERCOT_TZ, ct_day_bounds, delivery_day_of

DAM_CLOSE_HOUR = 10


def dam_close(delivery_day: date | pd.Timestamp) -> pd.Timestamp:
    """The UTC instant the model must predict from: 10:00 CT on D-1."""
    day = pd.Timestamp(delivery_day).tz_localize(None).normalize()
    local = (day - pd.Timedelta(days=1)) + pd.Timedelta(hours=DAM_CLOSE_HOUR)
    return local.tz_localize(ERCOT_TZ).tz_convert("UTC")


def history_cutoff(delivery_day: date | pd.Timestamp) -> pd.Timestamp:
    """Exclusive UTC shadow-price bound: midnight CT on delivery day D.

    This admits all of D-1, whose DAM outcome cleared on D-2, without admitting
    D itself—the target.  The distinction is deliberately tested from both sides.
    """
    day = pd.Timestamp(delivery_day).tz_localize(None).normalize()
    return day.tz_localize(ERCOT_TZ).tz_convert("UTC")


def dam_close_expr(ts_col: str) -> str:
    """Return the SQL expression for an interval's DAM-close instant."""
    _DAM_CLOSE_SQL = """
    ((date_trunc('day', {ts} AT TIME ZONE '{tz}') - interval '1 day'
      + interval '{hour} hours') AT TIME ZONE '{tz}')
"""
    return _DAM_CLOSE_SQL.format(ts=ts_col, tz=ERCOT_TZ, hour=DAM_CLOSE_HOUR)


def vintage_cutoff_expr(ts_col: str,
                        vintage_cutoff: pd.Timestamp | None) -> tuple[str, tuple]:
    """Return the DAM-close predicate, optionally capped at a run fire instant.

    The cap recreates the information set of a historical preview; uncapped
    callers retain the original SQL expression and query plan.
    """
    close = dam_close_expr(ts_col)
    if vintage_cutoff is None:
        return close, ()
    return f"LEAST({close}, %s)", (pd.Timestamp(vintage_cutoff),)
