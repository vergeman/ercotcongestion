"""Tests for GET /conditions_range's DAM-close snapshot."""
from __future__ import annotations

from datetime import datetime, timezone


START = "2026-03-25T18:00:00Z"  # 2026-03-25 13:00 CT
END = "2026-03-25T19:00:00Z"    # 2026-03-25 14:00 CT
RANGE_START = "2026-01-01T00:00:00Z"
RANGE_END_336H = "2026-01-15T00:00:00Z"
RANGE_END_337H = "2026-01-15T01:00:00Z"
T0 = datetime(2026, 3, 25, 18, tzinfo=timezone.utc)
T1 = datetime(2026, 3, 25, 19, tzinfo=timezone.utc)
D_MINUS_1 = "2026-03-24"


def _load_row(system_total=520.0, **overrides):
    row = {
        "interval_ts": T0, "coast": 100.0, "east": 10.0, "far_west": 20.0,
        "north": 30.0, "north_central": 200.0, "south_central": 50.0,
        "southern": 40.0, "west": 60.0, "system_total": system_total,
    }
    row.update(overrides)
    return row


def _wind_row(system_val=16.0, **overrides):
    row = {
        "interval_ts": T0, "stwpf_panhandle": 1.0, "stwpf_coastal": 2.0,
        "stwpf_south": 3.0, "stwpf_west": 4.0, "stwpf_north": 5.0,
        "stwpf_system_wide": system_val,
    }
    row.update(overrides)
    return row


def _solar_row(system_val=22.0, **overrides):
    row = {
        "interval_ts": T0, "stppf_centerwest": 1.0, "stppf_northwest": 2.0,
        "stppf_farwest": 3.0, "stppf_fareast": 4.0, "stppf_southeast": 5.0,
        "stppf_centereast": 6.0, "stppf_system_wide": system_val,
    }
    row.update(overrides)
    return row


def _outage_row(posted_date, fuel_type, mw, planned_end):
    return {
        "posted_date": datetime.strptime(posted_date, "%Y-%m-%d").date(),
        "fuel_type": fuel_type,
        "effective_mw_reduction": mw,
        "planned_end_date": planned_end,
    }


def _queue_all(fake_pool, *, load=None, wind=None, solar=None, outages=None):
    fake_pool.cursor.queue(load or [])
    fake_pool.cursor.queue(wind or [])
    fake_pool.cursor.queue(solar or [])
    fake_pool.cursor.queue(outages or [])


def test_conditions_range_accepts_a_336_hour_window(client, fake_pool):
    response = client.get("/conditions_range", params={"start": RANGE_START, "end": RANGE_END_336H})

    assert response.status_code == 503
    assert len(fake_pool.cursor.queries) == 4


def test_conditions_range_rejects_invalid_windows_before_queries(client, fake_pool):
    for end in (RANGE_END_337H, "2025-12-31T23:00:00Z"):
        response = client.get("/conditions_range", params={"start": RANGE_START, "end": end})
        assert response.status_code == 422

    assert fake_pool.cursor.queries == []


def test_conditions_range_returns_dam_close_snapshot(client, fake_pool):
    _queue_all(
        fake_pool,
        load=[_load_row()],
        wind=[_wind_row()],
        solar=[_solar_row()],
        outages=[_outage_row(D_MINUS_1, "Wind", 50.0, T1)],
    )

    response = client.get("/conditions_range", params={"start": START, "end": END})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    entry = body["entries"][0]
    assert entry["load"][-1] == {"zone": "system", "dam_close_mw": 520.0}
    assert entry["wind"][-1] == {"region": "system", "dam_close_mw": 16.0}
    assert entry["solar"][-1] == {"region": "system", "dam_close_mw": 22.0}
    outages = {row["fuel"]: row for row in entry["outages"]}
    assert outages["wind"]["dam_close_mw"] == 50.0
    assert outages["total"]["dam_close_mw"] == 50.0


def test_conditions_queries_use_dam_close_and_never_actual_tables(client, fake_pool):
    _queue_all(fake_pool, load=[_load_row()])

    response = client.get("/conditions_range", params={"start": START, "end": END})

    assert response.status_code == 200
    sql = "\n".join(query for query, _ in fake_pool.cursor.queries)
    assert "posted_datetime <=" in sql
    assert "interval '1 day'" in sql
    assert "interval '10 hours'" in sql
    assert "load_by_zone" not in sql
    assert "wind_hourly_regional" not in sql
    assert "solar_hourly_regional" not in sql


def test_conditions_range_missing_sources_are_empty_lists(client, fake_pool):
    _queue_all(fake_pool, load=[_load_row()])

    response = client.get("/conditions_range", params={"start": START, "end": END})

    entry = response.json()["entries"][0]
    assert entry["wind"] == []
    assert entry["solar"] == []
    assert entry["outages"] == []
    assert {row["zone"] for row in entry["load"]} == {
        "coast", "east", "far_west", "north", "north_central", "south_central", "southern", "west", "system",
    }


def test_conditions_outages_use_d_minus_1_expected_snapshot(client, fake_pool):
    _queue_all(
        fake_pool,
        outages=[_outage_row(D_MINUS_1, "Natural Gas", 100.0, T1)],
    )

    response = client.get("/conditions_range", params={"start": START, "end": END})

    outages = {row["fuel"]: row for row in response.json()["entries"][0]["outages"]}
    assert outages["gas"]["dam_close_mw"] == 100.0


def test_conditions_range_empty_window_returns_503(client, fake_pool):
    _queue_all(fake_pool)

    response = client.get("/conditions_range", params={"start": START, "end": END})

    assert response.status_code == 503
