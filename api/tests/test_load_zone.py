"""Tests for GET /load_zone_range."""
from __future__ import annotations

from datetime import datetime, timezone


START = "2026-03-25T00:00:00Z"
END = "2026-03-25T23:00:00Z"
T0 = datetime(2026, 3, 25, 22, tzinfo=timezone.utc)


def _actual_row(**overrides):
    row = {
        "interval_ts": T0,
        "coast": 10_000.0, "east": 1_000.0, "far_west": 2_000.0, "north": 3_000.0,
        "north_central": 20_000.0, "south_central": 5_000.0, "southern": 4_000.0,
        "west": 6_000.0, "total": 51_000.0,
    }
    row.update(overrides)
    return row


def _forecast_row(**overrides):
    row = {
        "interval_ts": T0,
        "coast": 10_500.0, "east": 1_100.0, "far_west": 2_100.0, "north": 3_100.0,
        "north_central": 20_500.0, "south_central": 5_100.0, "southern": 4_100.0,
        "west": 6_100.0, "system_total": 52_500.0,
    }
    row.update(overrides)
    return row


def test_load_zone_range_merges_actual_and_forecast(client, fake_pool):
    fake_pool.cursor.queue([_actual_row()])
    fake_pool.cursor.queue([_forecast_row()])

    response = client.get("/load_zone_range", params={"start": START, "end": END})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    zones = {z["zone"]: z for z in body["entries"][0]["zones"]}
    assert zones["coast"]["actual_mw"] == 10_000.0
    assert zones["coast"]["forecast_mw"] == 10_500.0
    assert zones["system"]["actual_mw"] == 51_000.0
    assert zones["system"]["forecast_mw"] == 52_500.0
    assert set(zones) == {
        "coast", "east", "far_west", "north", "north_central",
        "south_central", "southern", "west", "system",
    }

    forecast_sql, _ = fake_pool.cursor.queries[1]
    assert "load_forecast_zonal" in forecast_sql
    assert "posted_datetime <= interval_ts" in forecast_sql


def test_load_zone_range_forecast_only_hour_has_null_actual(client, fake_pool):
    """A pre-market hour: only a forecast has posted yet."""
    fake_pool.cursor.queue([])
    fake_pool.cursor.queue([_forecast_row()])

    response = client.get("/load_zone_range", params={"start": START, "end": END})

    assert response.status_code == 200
    zones = {z["zone"]: z for z in response.json()["entries"][0]["zones"]}
    assert zones["coast"]["actual_mw"] is None
    assert zones["coast"]["forecast_mw"] == 10_500.0


def test_load_zone_range_empty_window_returns_503(client, fake_pool):
    fake_pool.cursor.queue([])
    fake_pool.cursor.queue([])

    response = client.get("/load_zone_range", params={"start": START, "end": END})

    assert response.status_code == 503
