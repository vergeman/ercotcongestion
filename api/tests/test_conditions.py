"""Tests for GET /conditions_range.

Query order per request (see conditions.py's `get_conditions_range`): load
actual, load forecast, wind actual, wind forecast, solar actual, solar
forecast, outages — seven `cur.execute` calls, so seven queued responses.
"""
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
D_SAME = "2026-03-25"


def _wind_row(prefix, system_val, **overrides):
    row = {
        "interval_ts": T0,
        f"{prefix}_panhandle": 1.0, f"{prefix}_coastal": 2.0, f"{prefix}_south": 3.0,
        f"{prefix}_west": 4.0, f"{prefix}_north": 5.0, f"{prefix}_system_wide": system_val,
    }
    row.update(overrides)
    return row


def _solar_row(prefix, system_val, **overrides):
    row = {
        "interval_ts": T0,
        f"{prefix}_centerwest": 1.0, f"{prefix}_northwest": 2.0, f"{prefix}_farwest": 3.0,
        f"{prefix}_fareast": 4.0, f"{prefix}_southeast": 5.0, f"{prefix}_centereast": 6.0,
        f"{prefix}_system_wide": system_val,
    }
    row.update(overrides)
    return row


def _outage_row(posted_date, fuel_type, mw, start, end=None, planned_end=None):
    return {
        "posted_date": datetime.strptime(posted_date, "%Y-%m-%d").date(),
        "fuel_type": fuel_type,
        "effective_mw_reduction": mw,
        "actual_outage_start": start,
        "actual_end_date": end,
        "planned_end_date": planned_end,
    }


def _queue_all(fake_pool, *, load_actual=None, load_forecast=None,
                wind_actual=None, wind_forecast=None,
                solar_actual=None, solar_forecast=None, outages=None):
    fake_pool.cursor.queue(load_actual or [])
    fake_pool.cursor.queue(load_forecast or [])
    fake_pool.cursor.queue(wind_actual or [])
    fake_pool.cursor.queue(wind_forecast or [])
    fake_pool.cursor.queue(solar_actual or [])
    fake_pool.cursor.queue(solar_forecast or [])
    fake_pool.cursor.queue(outages or [])


def test_conditions_range_accepts_a_336_hour_window(client, fake_pool):
    response = client.get("/conditions_range", params={"start": RANGE_START, "end": RANGE_END_336H})

    assert response.status_code == 503
    assert len(fake_pool.cursor.queries) == 7


def test_conditions_range_rejects_invalid_windows_before_queries(client, fake_pool):
    for end in (RANGE_END_337H, "2025-12-31T23:00:00Z"):
        response = client.get("/conditions_range", params={"start": RANGE_START, "end": end})
        assert response.status_code == 422

    assert fake_pool.cursor.queries == []


def test_conditions_range_merges_all_four_sources(client, fake_pool):
    load_actual = {"interval_ts": T0, "coast": 100.0, "east": 10.0, "far_west": 20.0,
                   "north": 30.0, "north_central": 200.0, "south_central": 50.0,
                   "southern": 40.0, "west": 60.0, "total": 510.0}
    load_forecast = {**{k: v for k, v in load_actual.items() if k != "total"},
                      "system_total": 520.0}
    _queue_all(
        fake_pool,
        load_actual=[load_actual],
        load_forecast=[load_forecast],
        wind_actual=[_wind_row("gen", 15.0)],
        wind_forecast=[_wind_row("stwpf", 16.0)],
        solar_actual=[_solar_row("gen", 21.0)],
        solar_forecast=[_solar_row("stppf", 22.0)],
        outages=[_outage_row(D_SAME, "Wind", 50.0, T0, planned_end=T1)],
    )

    response = client.get("/conditions_range", params={"start": START, "end": END})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2  # T0 and T1, hourly grid

    entry0 = body["entries"][0]
    load = {z["zone"]: z for z in entry0["load"]}
    assert load["coast"]["actual_mw"] == 100.0
    assert load["system"]["actual_mw"] == 510.0
    assert load["system"]["forecast_mw"] == 520.0

    wind = {r["region"]: r for r in entry0["wind"]}
    assert wind["panhandle"]["actual_mw"] == 1.0
    assert wind["system"]["actual_mw"] == 15.0
    assert wind["system"]["forecast_mw"] == 16.0

    solar = {r["region"]: r for r in entry0["solar"]}
    assert solar["centerwest"]["actual_mw"] == 1.0
    assert solar["system"]["forecast_mw"] == 22.0

    outages = {f["fuel"]: f for f in entry0["outages"]}
    assert outages["wind"]["actual_mw"] == 50.0
    assert outages["total"]["actual_mw"] == 50.0


def test_conditions_range_missing_source_for_hour_is_empty_list(client, fake_pool):
    """No wind/solar/outages rows at all -> those lists are empty, not erroring."""
    load_actual = {"interval_ts": T0, "coast": 100.0, "east": 10.0, "far_west": 20.0,
                   "north": 30.0, "north_central": 200.0, "south_central": 50.0,
                   "southern": 40.0, "west": 60.0, "total": 510.0}
    _queue_all(fake_pool, load_actual=[load_actual])

    response = client.get("/conditions_range", params={"start": START, "end": END})

    assert response.status_code == 200
    entry0 = response.json()["entries"][0]
    assert entry0["wind"] == []
    assert entry0["solar"] == []
    assert entry0["outages"] == []
    assert {z["zone"] for z in entry0["load"]} == {
        "coast", "east", "far_west", "north", "north_central",
        "south_central", "southern", "west", "system",
    }


def test_conditions_range_outages_forecast_uses_d_minus_1_vintage(client, fake_pool):
    _queue_all(
        fake_pool,
        outages=[
            _outage_row(D_MINUS_1, "Natural Gas", 100.0, T0, planned_end=T1),
            _outage_row(D_SAME, "Natural Gas", 100.0, T0,
                        end=datetime(2026, 3, 25, 17, tzinfo=timezone.utc)),
        ],
    )

    response = client.get("/conditions_range", params={"start": START, "end": END})

    outages = {f["fuel"]: f for f in response.json()["entries"][0]["outages"]}
    assert outages["gas"]["forecast_mw"] == 100.0  # D-1 vintage: still "planned" out
    assert outages["gas"]["actual_mw"] == 0.0       # D vintage: already ended


def test_conditions_range_empty_window_returns_503(client, fake_pool):
    _queue_all(fake_pool)

    response = client.get("/conditions_range", params={"start": START, "end": END})

    assert response.status_code == 503
