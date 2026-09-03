"""Central-time delivery-day conventions shared by compute jobs.

All persisted intervals are UTC instants, while ERCOT delivery dates are Central
Time calendar dates.  These helpers deliberately use calendar-day arithmetic so
the spring-forward and fall-back blocks remain 23 and 25 hours respectively.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd


ERCOT_TZ = "America/Chicago"


def localize_ct(x) -> pd.Timestamp:
    """Coerce a date/timestamp to the equivalent CT-zoned instant."""
    ts = pd.Timestamp(x)
    if pd.isna(ts):
        return ts
    return ts.tz_convert(ERCOT_TZ) if ts.tzinfo is not None else ts.tz_localize(ERCOT_TZ)


def unique_days(index) -> pd.DatetimeIndex:
    """Normalize in the index's own tz, without re-zoning to CT."""
    return pd.DatetimeIndex(pd.Index(index).normalize().unique()).sort_values()


def ct_day_bounds(delivery_day) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return DST-aware UTC ``[start, end)`` bounds for one CT delivery day."""
    ts = pd.Timestamp(delivery_day)
    start = (ts.tz_convert(ERCOT_TZ) if ts.tzinfo is not None
             else ts.tz_localize(ERCOT_TZ)).normalize()
    return start.tz_convert("UTC"), (start + pd.DateOffset(days=1)).tz_convert("UTC")


def delivery_bounds(delivery_day) -> tuple[datetime, datetime]:
    """Return Python-datetime UTC ``[start, end)`` bounds for one ERCOT day."""
    start, end = ct_day_bounds(delivery_day)
    return start.to_pydatetime(), end.to_pydatetime()


def normalize_ct_day(delivery_day) -> pd.Timestamp:
    """Return the UTC instant marking ``delivery_day``'s CT midnight."""
    start, _ = ct_day_bounds(delivery_day)
    return start


def delivery_day_of(ts: pd.Timestamp | pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Return the timezone-naive CT midnight for each UTC interval."""
    return (pd.DatetimeIndex(pd.to_datetime(ts)).tz_convert(ERCOT_TZ)
            .normalize().tz_localize(None))


def delivery_date_of(ts: pd.Series) -> pd.Series:
    """Return the CT calendar-date label for each tz-aware UTC interval."""
    return ts.dt.tz_convert(ERCOT_TZ).dt.date
