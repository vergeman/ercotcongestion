"""Availability rules for the μ feature panel.

The prediction is made at DAM close: 10:00 CT on D-1.  Every feature must be
answerable from that vantage point.  Forecasts and outages use their newest
``posted_datetime <= DAM close`` vintage; day D's shadow prices are never
available, while all of D-1 is public and legal history.
"""
from __future__ import annotations

from datetime import date

import pandas as pd


ERCOT_TZ = "America/Chicago"
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


def delivery_day_of(ts: pd.Timestamp | pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Return the ERCOT-local delivery day for each interval."""
    return (pd.DatetimeIndex(pd.to_datetime(ts)).tz_convert(ERCOT_TZ)
            .normalize().tz_localize(None))


def ct_day_bounds(delivery_day) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return DST-aware UTC ``[start, end)`` bounds for one CT delivery day.

    ``DateOffset``, rather than an absolute-time ``Timedelta``, preserves the
    23/24/25-hour length of spring-forward, ordinary, and fall-back days.
    """
    ts = pd.Timestamp(delivery_day)
    start = (ts.tz_convert(ERCOT_TZ) if ts.tzinfo is not None
             else ts.tz_localize(ERCOT_TZ)).normalize()
    return start.tz_convert("UTC"), (start + pd.DateOffset(days=1)).tz_convert("UTC")


_DAM_CLOSE_SQL = """
    ((date_trunc('day', {ts} AT TIME ZONE '{tz}') - interval '1 day'
      + interval '{hour} hours') AT TIME ZONE '{tz}')
"""


def dam_close_expr(ts_col: str) -> str:
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
