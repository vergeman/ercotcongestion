"""dam_shadow_covers_window — the guard that tells a fully-published DAM op-day
apart from the ~5h prior-op-day tail a UTC delivery window always catches (0127).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from compute.sf.panels import DAM_SHADOW_MIN_COVER_HOURS, dam_shadow_covers_window

LO = pd.Timestamp("2026-07-30", tz="UTC")   # a UTC delivery-window start


def test_none_and_nat_are_uncovered():
    assert dam_shadow_covers_window(None, LO) is False
    assert dam_shadow_covers_window(pd.NaT, LO) is False


def test_prior_opday_tail_is_uncovered():
    # Only 00:00–04:00Z present == the tail of the op-day before D; the current
    # op-day's report has not landed. Must NOT read as "DAM published".
    assert dam_shadow_covers_window(LO + pd.Timedelta(hours=4), LO) is False


def test_full_day_afternoon_peak_is_covered():
    # A published op-day binds through the afternoon peak (~22:00Z here).
    assert dam_shadow_covers_window(LO + pd.Timedelta(hours=22), LO) is True


def test_threshold_boundary_is_inclusive():
    at = LO + pd.Timedelta(hours=DAM_SHADOW_MIN_COVER_HOURS)
    just_under = LO + pd.Timedelta(hours=DAM_SHADOW_MIN_COVER_HOURS - 1)
    assert dam_shadow_covers_window(at, LO) is True
    assert dam_shadow_covers_window(just_under, LO) is False


def test_accepts_pydatetime_from_sql():
    # The h2 gate feeds max(interval_ts) straight from psycopg (a tz-aware datetime).
    assert dam_shadow_covers_window(
        datetime(2026, 7, 30, 4, tzinfo=timezone.utc), LO) is False
    assert dam_shadow_covers_window(
        datetime(2026, 7, 30, 22, tzinfo=timezone.utc), LO) is True
