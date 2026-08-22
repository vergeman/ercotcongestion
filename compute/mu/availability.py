"""Availability rules for the μ feature panel."""
from __future__ import annotations

from datetime import date

import pandas as pd


ERCOT_TZ = "America/Chicago"
DAM_CLOSE_HOUR = 10


def dam_close(delivery_day: date | pd.Timestamp) -> pd.Timestamp:
    """Return the UTC DAM-close instant for a delivery day."""
    day = pd.Timestamp(delivery_day).tz_localize(None).normalize()
    local = (day - pd.Timedelta(days=1)) + pd.Timedelta(hours=DAM_CLOSE_HOUR)
    return local.tz_localize(ERCOT_TZ).tz_convert("UTC")


def history_cutoff(delivery_day: date | pd.Timestamp) -> pd.Timestamp:
    """Return the exclusive UTC shadow-price cutoff at DAM close."""
    day = pd.Timestamp(delivery_day).tz_localize(None).normalize()
    return day.tz_localize(ERCOT_TZ).tz_convert("UTC")


def delivery_day_of(ts: pd.Timestamp | pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Return the ERCOT-local delivery day for each interval."""
    return (pd.DatetimeIndex(pd.to_datetime(ts)).tz_convert(ERCOT_TZ)
            .normalize().tz_localize(None))


def ct_day_bounds(delivery_day) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return DST-aware UTC ``[start, end)`` bounds for one CT delivery day."""
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
    """Return the SQL availability predicate and its optional fire-time bound."""
    close = dam_close_expr(ts_col)
    if vintage_cutoff is None:
        return close, ()
    return f"LEAST({close}, %s)", (pd.Timestamp(vintage_cutoff),)
