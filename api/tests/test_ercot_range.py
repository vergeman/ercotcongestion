"""Tests for compact GET /ercot_range."""
from datetime import datetime, timezone


T0 = datetime(2026, 3, 25, 22, tzinfo=timezone.utc)
T1 = datetime(2026, 3, 25, 23, tzinfo=timezone.utc)
RANGE_START = "2026-01-01T00:00:00Z"
RANGE_END_336H = "2026-01-15T00:00:00Z"
RANGE_END_337H = "2026-01-15T01:00:00Z"


def test_compact_range_accepts_a_336_hour_window(client, fake_pool):
    response = client.get("/ercot_range", params={"start": RANGE_START, "end": RANGE_END_336H})

    assert response.status_code == 503
    assert len(fake_pool.cursor.queries) == 1


def test_compact_range_rejects_invalid_windows_before_queries(client, fake_pool):
    for end in (RANGE_END_337H, "2025-12-31T23:00:00Z"):
        response = client.get("/ercot_range", params={"start": RANGE_START, "end": end})
        assert response.status_code == 422

    assert fake_pool.cursor.queries == []


def test_compact_range_shares_sp_index_and_combines_realized_values(client, fake_pool):
    fake_pool.cursor.queue([
        {"interval_ts": T0, "settlement_point": "LZ_NORTH", "dam_spp": 28.0,
         "system_lambda": 30.0},
        {"interval_ts": T0, "settlement_point": "LZ_SOUTH", "dam_spp": 42.0,
         "system_lambda": 30.0},
        {"interval_ts": T1, "settlement_point": "LZ_SOUTH", "dam_spp": 25.0,
         "system_lambda": 25.0},
    ])

    response = client.get("/ercot_range", params={
        "start": "2026-03-25T22:00:00Z", "end": "2026-03-25T23:00:00Z",
    })

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sp_ids"] == ["LZ_NORTH", "LZ_SOUTH"]
    assert body["entries"][0]["spp"] == [28.0, 42.0]
    assert body["entries"][0]["congestion"] == [-2.0, 12.0]
    assert body["entries"][0]["system_lambda"] == 30.0
    # Missing SPs preserve the shared index rather than changing positions.
    assert body["entries"][1]["spp"] == [None, 25.0]
    assert body["entries"][1]["congestion"] == [None, 0.0]
    assert len(fake_pool.cursor.queries) == 1


def test_compact_range_rounds_congestion_to_cents(client, fake_pool):
    fake_pool.cursor.queue([{
        "interval_ts": T0, "settlement_point": "LZ_SOUTH", "dam_spp": 42.345,
        "system_lambda": 30.0,
    }])

    response = client.get("/ercot_range", params={
        "start": "2026-03-25T22:00:00Z", "end": "2026-03-25T22:00:00Z",
    })

    assert response.status_code == 200, response.text
    assert response.json()["entries"][0]["congestion"] == [12.35]
