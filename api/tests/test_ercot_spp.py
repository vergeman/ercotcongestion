"""Tests for GET /ercot_spp_range."""
from __future__ import annotations

from datetime import datetime, timezone


START = "2026-03-25T00:00:00Z"
END = "2026-03-25T23:00:00Z"
T0 = datetime(2026, 3, 25, 22, tzinfo=timezone.utc)


def test_spp_range_includes_total_load_for_each_hour(client, fake_pool):
    fake_pool.cursor.queue([
        {
            "interval_ts": T0,
            "settlement_point": "LZ_SOUTH",
            "dam_spp": 42.0,
            "total_load_mw": 61_234.5,
        },
        {
            "interval_ts": T0,
            "settlement_point": "LZ_NORTH",
            "dam_spp": 28.0,
            "total_load_mw": 61_234.5,
        },
    ])

    response = client.get("/ercot_spp_range", params={"start": START, "end": END})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["entries"][0]["total_load_mw"] == 61_234.5
    assert {sp["sp_id"] for sp in body["entries"][0]["sps"]} == {
        "LZ_SOUTH",
        "LZ_NORTH",
    }
    sql, params = fake_pool.cursor.queries[0]
    assert "load_by_zone" in sql
    assert params == (
        datetime(2026, 3, 25, tzinfo=timezone.utc),
        datetime(2026, 3, 25, 23, tzinfo=timezone.utc),
        datetime(2026, 3, 25, tzinfo=timezone.utc),
        datetime(2026, 3, 25, 23, tzinfo=timezone.utc),
    )


def test_spp_range_allows_missing_total_load(client, fake_pool):
    fake_pool.cursor.queue([
        {
            "interval_ts": T0,
            "settlement_point": "LZ_SOUTH",
            "dam_spp": 42.0,
            "total_load_mw": None,
        },
    ])

    response = client.get("/ercot_spp_range", params={"start": START, "end": END})

    assert response.status_code == 200
    assert response.json()["entries"][0]["total_load_mw"] is None
