"""Tests for GET /ercot_state_range.

Congestion is ``SPP − system_λ`` computed from the DB at request time
(``ercot_dam_spp`` minus ``dam_system_lambda``), no run artifact. The fake
cursor is FIFO, so rows are queued in the order the endpoint's queries fire:
system_lambda first, then DAM SPP.
"""
from __future__ import annotations

from datetime import datetime, timezone

T0 = datetime(2026, 3, 25, 22, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 3, 25, 23, 0, tzinfo=timezone.utc)

START = "2026-03-25T22:00:00Z"
END = "2026-03-25T23:00:00Z"


def _get(client):
    return client.get("/ercot_state_range", params={"start": START, "end": END})


def test_congestion_is_spp_minus_system_lambda(client, fake_pool):
    fake_pool.cursor.queue([
        {"interval_ts": T0, "system_lambda": 30.0},
        {"interval_ts": T1, "system_lambda": 25.0},
    ])
    fake_pool.cursor.queue([
        {"interval_ts": T0, "settlement_point": "LZ_SOUTH", "dam_spp": 42.0},
        {"interval_ts": T0, "settlement_point": "LZ_NORTH", "dam_spp": 28.0},
        {"interval_ts": T1, "settlement_point": "LZ_SOUTH", "dam_spp": 25.0},
    ])

    r = _get(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 2

    e0 = body["entries"][0]
    assert e0["interval_ts"].startswith("2026-03-25T22:00")
    by_sp = {s["sp_id"]: s["congestion"] for s in e0["sps"]}
    assert by_sp["LZ_SOUTH"] == 12.0   # 42 − 30
    assert by_sp["LZ_NORTH"] == -2.0   # 28 − 30

    e1 = body["entries"][1]
    assert e1["sps"][0]["sp_id"] == "LZ_SOUTH"
    assert e1["sps"][0]["congestion"] == 0.0  # 25 − 25


def test_null_spp_yields_null_congestion(client, fake_pool):
    fake_pool.cursor.queue([{"interval_ts": T0, "system_lambda": 30.0}])
    fake_pool.cursor.queue([
        {"interval_ts": T0, "settlement_point": "LZ_SOUTH", "dam_spp": None},
    ])

    r = _get(client)
    assert r.status_code == 200, r.text
    assert r.json()["entries"][0]["sps"][0]["congestion"] is None


def test_hour_without_system_lambda_drops_out(client, fake_pool):
    """SPP at an hour with no matching system_λ is not emitted (join gap)."""
    fake_pool.cursor.queue([{"interval_ts": T0, "system_lambda": 30.0}])
    fake_pool.cursor.queue([
        {"interval_ts": T0, "settlement_point": "LZ_SOUTH", "dam_spp": 42.0},
        {"interval_ts": T1, "settlement_point": "LZ_SOUTH", "dam_spp": 99.0},
    ])

    r = _get(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    assert body["entries"][0]["interval_ts"].startswith("2026-03-25T22:00")


def test_empty_window_returns_503(client, fake_pool):
    fake_pool.cursor.queue([])  # no system_lambda
    fake_pool.cursor.queue([])  # no spp

    r = _get(client)
    assert r.status_code == 503
