"""NP1-346-ER ingest record builder (plan/0089 commit 2).

The parse/DB plumbing (unzip, INSERT) needs the container; what is worth pinning here is
the pure `to_records` mapping, and two facts the migration's key rests on:

  * the vintage `posted_date` comes from the caller (the archive document), not a row —
    every record in a snapshot carries the same one;
  * a unit code that appears twice in one snapshot yields TWO records, distinguished by
    `actual_outage_start` — keying on the unit code alone would silently drop rows.

`to_records` lives in `ercot_ingest/outage_parse.py` (pandas-only, no psycopg), imported
here via a path insert so this runs outside the container.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "ercot_ingest"))

from outage_parse import to_records  # noqa: E402


def _snapshot() -> pd.DataFrame:
    """Two rows sharing a unit code (concurrent outages), one blank-unit footer row."""
    return pd.DataFrame({
        "Resource Name":      ["FRNYPP", "FRNYPP", None],
        "Resource Unit Code": ["FRNYPP_ST10", "FRNYPP_ST10", None],
        "Fuel Type":          ["Natural Gas", "Natural Gas", None],
        "Outage Type":        ["Forced", "Maintenance Level 2", None],
        "Available MW Maximum":                [410, 410, None],
        "Available MW During Outage":          [0.0, 100.0, None],
        "Effective MW Reduction Due to Outage": [410.0, 310.0, None],
        # naive ERCOT Central; the two share a unit code but differ in start.
        "Actual Outage Start": [datetime(2025, 7, 12, 4, 6),
                                datetime(2025, 8, 1, 9, 0), None],
        "Planned End Date":    [datetime(2026, 7, 11, 23, 59), pd.NaT, None],
        "Actual End Date":     [pd.NaT, pd.NaT, None],
        "Nature Of Work":      ["turbine", "inspection", None],
    })


def test_vintage_is_the_caller_posted_date_on_every_record():
    recs = to_records(_snapshot(), date(2026, 7, 14))
    assert len(recs) == 2                       # the footer (blank unit code) is dropped
    assert all(r[0] == date(2026, 7, 14) for r in recs)


def test_repeated_unit_code_yields_distinct_records_keyed_by_start():
    recs = to_records(_snapshot(), date(2026, 7, 14))
    keys = {(r[0], r[1], r[2]) for r in recs}   # (posted_date, unit_code, start)
    assert len(keys) == 2                        # both survive — not collapsed to one
    assert all(r[1] == "FRNYPP_ST10" for r in recs)


def test_central_timestamps_convert_to_utc():
    recs = to_records(_snapshot(), date(2026, 7, 14))
    start = next(r[2] for r in recs if r[5] == "Forced")  # the "Forced" row's start
    # 2025-07-12 04:06 CDT (UTC-5) -> 09:06 UTC.
    assert start == datetime(2025, 7, 12, 9, 6, tzinfo=timezone.utc)


def test_missing_planned_and_actual_end_become_none_not_nan():
    recs = to_records(_snapshot(), date(2026, 7, 14))
    maint = next(r for r in recs if r[5] == "Maintenance Level 2")
    assert maint[9] is None and maint[10] is None     # planned_end, actual_end
    # and no NaN leaks into the numeric columns
    assert all(x is None or x == x for r in recs for x in r[6:9])


def test_row_with_no_outage_start_is_dropped():
    df = pd.DataFrame({
        "Resource Name": ["X"], "Resource Unit Code": ["X_G1"], "Fuel Type": ["Wind"],
        "Outage Type": ["Forced"], "Available MW Maximum": [10],
        "Available MW During Outage": [0.0],
        "Effective MW Reduction Due to Outage": [10.0],
        "Actual Outage Start": [pd.NaT], "Planned End Date": [pd.NaT],
        "Actual End Date": [pd.NaT], "Nature Of Work": ["x"],
    })
    assert to_records(df, date(2026, 7, 14)) == []
