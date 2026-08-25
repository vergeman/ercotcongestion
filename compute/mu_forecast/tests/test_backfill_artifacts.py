"""Tests for `backfill_artifacts`'s pure orchestration helpers (0133).

`main()` itself is DB/fit-heavy CLI plumbing exercised by the runbook, not unit
tests; `_fire_time_for` is the one piece of new logic worth pinning in isolation —
get the horizon/day arithmetic wrong here and a re-backfilled preview silently
reads a fresher covariate vintage than the live run ever could have.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from compute.jobs.backfill_artifacts import _fire_time_for


def test_final_fire_time_is_1700z_on_d_minus_1():
    assert _fire_time_for(date(2026, 7, 27), 1) == pd.Timestamp(
        "2026-07-26 17:00", tz="UTC")


def test_preview_fire_time_is_2015z_on_d_minus_2():
    assert _fire_time_for(date(2026, 7, 27), 2) == pd.Timestamp(
        "2026-07-25 20:15", tz="UTC")


def test_final_fire_time_is_after_dam_close_a_no_op_cap():
    """h1's fire time sits after D's DAM close (10:00 CT on D−1), so `LEAST` in
    the vintage predicate always picks DAM close — the cap changes nothing."""
    from compute.mu_forecast.panel.build import dam_close
    d = date(2026, 7, 27)
    assert _fire_time_for(d, 1) > dam_close(pd.Timestamp(d))


def test_preview_fire_time_is_well_before_dam_close_a_real_cap():
    """h2's fire time sits before D's DAM close, so `LEAST` genuinely restricts
    the read — the whole point of the vintage-faithful backfill."""
    from compute.mu_forecast.panel.build import dam_close
    d = date(2026, 7, 27)
    assert _fire_time_for(d, 2) < dam_close(pd.Timestamp(d))


def test_fire_times_are_dst_stable_utc_clock_times():
    """The cron fires at a fixed UTC instant regardless of the CT DST offset —
    unlike the CT delivery-day boundary itself, these are not CT-anchored."""
    assert _fire_time_for(date(2026, 3, 9), 1) == pd.Timestamp(
        "2026-03-08 17:00", tz="UTC")
    assert _fire_time_for(date(2026, 11, 2), 2) == pd.Timestamp(
        "2026-10-31 20:15", tz="UTC")
