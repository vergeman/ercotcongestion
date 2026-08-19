"""Tests for GET /generation_range."""
from __future__ import annotations

from datetime import datetime, timezone


START = "2026-03-25T00:00:00Z"
END = "2026-03-25T23:00:00Z"
T0 = datetime(2026, 3, 25, 22, tzinfo=timezone.utc)


def _wind_actual_row(**overrides):
    row = {
        "interval_ts": T0,
        "gen_panhandle": 100.0, "gen_coastal": 200.0, "gen_south": 300.0,
        "gen_west": 400.0, "gen_north": 500.0, "gen_system_wide": 1_500.0,
    }
    row.update(overrides)
    return row


def _wind_forecast_row(**overrides):
    row = {
        "interval_ts": T0,
        "stwpf_panhandle": 110.0, "stwpf_coastal": 210.0, "stwpf_south": 310.0,
        "stwpf_west": 410.0, "stwpf_north": 510.0, "stwpf_system_wide": 1_550.0,
    }
    row.update(overrides)
    return row


def _solar_actual_row(**overrides):
    row = {
        "interval_ts": T0,
        "gen_centerwest": 50.0, "gen_northwest": 60.0, "gen_farwest": 70.0,
        "gen_fareast": 80.0, "gen_southeast": 90.0, "gen_centereast": 100.0,
        "gen_system_wide": 450.0,
    }
    row.update(overrides)
    return row


def _solar_forecast_row(**overrides):
    row = {
        "interval_ts": T0,
        "stppf_centerwest": 55.0, "stppf_northwest": 65.0, "stppf_farwest": 75.0,
        "stppf_fareast": 85.0, "stppf_southeast": 95.0, "stppf_centereast": 105.0,
        "stppf_system_wide": 480.0,
    }
    row.update(overrides)
    return row


def test_generation_range_merges_wind_and_solar(client, fake_pool):
    fake_pool.cursor.queue([_wind_actual_row()])
    fake_pool.cursor.queue([_wind_forecast_row()])
    fake_pool.cursor.queue([_solar_actual_row()])
    fake_pool.cursor.queue([_solar_forecast_row()])

    response = client.get("/generation_range", params={"start": START, "end": END})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    entry = body["entries"][0]

    wind = {r["region"]: r for r in entry["wind"]}
    assert wind["panhandle"]["actual_mw"] == 100.0
    assert wind["panhandle"]["forecast_mw"] == 110.0
    assert wind["system"]["actual_mw"] == 1_500.0
    assert wind["system"]["forecast_mw"] == 1_550.0
    assert set(wind) == {"panhandle", "coastal", "south", "west", "north", "system"}

    solar = {r["region"]: r for r in entry["solar"]}
    assert solar["centerwest"]["actual_mw"] == 50.0
    assert solar["centerwest"]["forecast_mw"] == 55.0
    assert set(solar) == {
        "centerwest", "northwest", "farwest", "fareast", "southeast",
        "centereast", "system",
    }

    forecast_sql, _ = fake_pool.cursor.queries[1]
    assert "wind_forecast_regional" in forecast_sql
    assert "posted_datetime <= interval_ts" in forecast_sql


def test_generation_range_wind_only_hour_has_null_solar(client, fake_pool):
    fake_pool.cursor.queue([_wind_actual_row()])
    fake_pool.cursor.queue([])
    fake_pool.cursor.queue([])
    fake_pool.cursor.queue([])

    response = client.get("/generation_range", params={"start": START, "end": END})

    assert response.status_code == 200
    entry = response.json()["entries"][0]
    assert entry["solar"] == []
    assert {r["region"] for r in entry["wind"]} == {
        "panhandle", "coastal", "south", "west", "north", "system",
    }


def test_generation_range_empty_window_returns_503(client, fake_pool):
    fake_pool.cursor.queue([])
    fake_pool.cursor.queue([])
    fake_pool.cursor.queue([])
    fake_pool.cursor.queue([])

    response = client.get("/generation_range", params={"start": START, "end": END})

    assert response.status_code == 503
