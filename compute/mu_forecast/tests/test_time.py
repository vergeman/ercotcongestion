"""Contracts for the shared CT delivery-time helpers."""
from __future__ import annotations

import pandas as pd
import pytest

from compute.time import (ct_day_bounds, delivery_date_of, delivery_day_of,
                          normalize_ct_day)


@pytest.mark.parametrize(
    ("day", "start", "end", "hours"),
    [
        ("2026-01-15", "2026-01-15 06:00", "2026-01-16 06:00", 24),
        ("2026-03-08", "2026-03-08 06:00", "2026-03-09 05:00", 23),
        ("2026-07-30", "2026-07-30 05:00", "2026-07-31 05:00", 24),
        ("2026-11-01", "2026-11-01 05:00", "2026-11-02 06:00", 25),
    ],
)
def test_ct_day_bounds_cover_each_delivery_block(day, start, end, hours):
    lo, hi = ct_day_bounds(day)

    assert lo == pd.Timestamp(start, tz="UTC")
    assert hi == pd.Timestamp(end, tz="UTC")
    assert hi - lo == pd.Timedelta(hours=hours)
    assert normalize_ct_day(lo) == lo
    assert (hi - pd.Timedelta(hours=1)).tz_convert("America/Chicago").hour == 23


@pytest.mark.parametrize("horizon", [1, 2])
def test_ct_day_bounds_keep_horizon_labels_at_utc_seams(horizon):
    day = pd.Timestamp("2026-03-08") + pd.Timedelta(days=horizon)
    lo, hi = ct_day_bounds(day)
    timestamps = pd.Series([lo, hi - pd.Timedelta(hours=1)])

    assert delivery_date_of(timestamps).tolist() == [day.date(), day.date()]
    assert delivery_day_of(timestamps).tolist() == [day, day]


def test_delivery_date_of_uses_ct_instead_of_the_utc_calendar_date():
    seam = pd.Series(pd.to_datetime(["2026-07-31 00:00:00+00:00"]))

    assert delivery_date_of(seam).tolist() == [pd.Timestamp("2026-07-30").date()]
