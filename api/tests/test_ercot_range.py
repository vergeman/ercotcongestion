"""Tests for compact GET /ercot_range."""
from datetime import datetime, timezone


T0 = datetime(2026, 3, 25, 22, tzinfo=timezone.utc)
T1 = datetime(2026, 3, 25, 23, tzinfo=timezone.utc)


def test_compact_range_shares_sp_index_and_combines_realized_values(client, fake_pool):
    fake_pool.cursor.queue([
        {"interval_ts": T0, "settlement_point": "LZ_NORTH", "dam_spp": 28.0,
         "system_lambda": 30.0, "total_load_mw": 61_000.0},
        {"interval_ts": T0, "settlement_point": "LZ_SOUTH", "dam_spp": 42.0,
         "system_lambda": 30.0, "total_load_mw": 61_000.0},
        {"interval_ts": T1, "settlement_point": "LZ_SOUTH", "dam_spp": 25.0,
         "system_lambda": 25.0, "total_load_mw": 60_500.0},
    ])

    response = client.get("/ercot_range", params={
        "start": "2026-03-25T22:00:00Z", "end": "2026-03-25T23:00:00Z",
    })

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sp_ids"] == ["LZ_NORTH", "LZ_SOUTH"]
    assert body["entries"][0]["spp"] == [28.0, 42.0]
    assert body["entries"][0]["congestion"] == [-2.0, 12.0]
    # Missing SPs preserve the shared index rather than changing positions.
    assert body["entries"][1]["spp"] == [None, 25.0]
    assert body["entries"][1]["congestion"] == [None, 0.0]
    assert len(fake_pool.cursor.queries) == 1


def test_compact_range_rounds_congestion_to_cents(client, fake_pool):
    fake_pool.cursor.queue([{
        "interval_ts": T0, "settlement_point": "LZ_SOUTH", "dam_spp": 42.345,
        "system_lambda": 30.0, "total_load_mw": None,
    }])

    response = client.get("/ercot_range", params={
        "start": "2026-03-25T22:00:00Z", "end": "2026-03-25T22:00:00Z",
    })

    assert response.status_code == 200, response.text
    assert response.json()["entries"][0]["congestion"] == [12.35]
