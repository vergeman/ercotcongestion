"""Tests for GET /outages_range."""
from __future__ import annotations

from datetime import datetime, timezone


# D (delivery day) = 2026-03-25 (UTC-CT boundary matters at the edges, so keep
# hours mid-day CT to sidestep DST/UTC-offset conversion entirely).
START = "2026-03-25T18:00:00Z"  # 2026-03-25 13:00 CT
END = "2026-03-25T19:00:00Z"    # 2026-03-25 14:00 CT
T0 = datetime(2026, 3, 25, 18, tzinfo=timezone.utc)
T1 = datetime(2026, 3, 25, 19, tzinfo=timezone.utc)

D_MINUS_1 = "2026-03-24"  # admissible forecast vintage (posted <= D-1)
D_SAME = "2026-03-25"     # admissible actual vintage (posted <= D)


def _row(posted_date, fuel_type, mw, start, end=None, planned_end=None):
    return {
        "posted_date": datetime.strptime(posted_date, "%Y-%m-%d").date(),
        "fuel_type": fuel_type,
        "effective_mw_reduction": mw,
        "actual_outage_start": start,
        "actual_end_date": end,
        "planned_end_date": planned_end,
    }


def test_outages_range_splits_forecast_and_actual_vintage(client, fake_pool):
    fake_pool.cursor.queue([
        # D-1 vintage: still shows this gas outage "planned" through the hour.
        _row(D_MINUS_1, "Natural Gas", 100.0, T0, planned_end=T1),
        # D vintage: the outage actually ended before T0 (excluded from actual).
        _row(D_SAME, "Natural Gas", 100.0, T0, end=datetime(2026, 3, 25, 17, tzinfo=timezone.utc)),
        # D vintage: a wind outage genuinely active at T0.
        _row(D_SAME, "Wind", 50.0, T0, planned_end=T1),
    ])

    response = client.get("/outages_range", params={"start": START, "end": END})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2  # T0 and T1, hourly grid
    entry0 = body["entries"][0]
    fuels = {f["fuel"]: f for f in entry0["fuels"]}

    # Forecast side reads the D-1 vintage: the gas outage still "planned" out.
    assert fuels["gas"]["forecast_mw"] == 100.0
    # Actual side reads the D vintage: gas already ended (excluded), wind active.
    assert fuels["gas"]["actual_mw"] == 0.0
    assert fuels["wind"]["actual_mw"] == 50.0
    assert fuels["total"]["actual_mw"] == 50.0
    assert set(fuels) == {"gas", "wind", "solar", "coal", "other", "hydro", "total"}


def test_outages_range_buckets_coal_and_hydro_out_of_other(client, fake_pool):
    fake_pool.cursor.queue([
        _row(D_SAME, "Lignite", 10.0, T0, planned_end=T1),
        _row(D_SAME, "Water", 5.0, T0, planned_end=T1),
        _row(D_SAME, "Nuclear", 20.0, T0, planned_end=T1),
    ])

    response = client.get("/outages_range", params={"start": START, "end": END})

    fuels = {f["fuel"]: f for f in response.json()["entries"][0]["fuels"]}
    assert fuels["coal"]["actual_mw"] == 10.0
    assert fuels["hydro"]["actual_mw"] == 5.0
    assert fuels["other"]["actual_mw"] == 20.0
    assert fuels["total"]["actual_mw"] == 35.0


def test_outages_range_no_snapshot_before_window_is_null_not_zero(client, fake_pool):
    """A window with only a D-vintage (no D-1) leaves forecast null, not 0."""
    fake_pool.cursor.queue([
        _row(D_SAME, "Wind", 50.0, T0, planned_end=T1),
    ])

    response = client.get("/outages_range", params={"start": START, "end": END})

    fuels = {f["fuel"]: f for f in response.json()["entries"][0]["fuels"]}
    assert fuels["wind"]["forecast_mw"] is None
    assert fuels["wind"]["actual_mw"] == 50.0


def test_outages_range_empty_window_returns_503(client, fake_pool):
    fake_pool.cursor.queue([])

    response = client.get("/outages_range", params={"start": START, "end": END})

    assert response.status_code == 503
