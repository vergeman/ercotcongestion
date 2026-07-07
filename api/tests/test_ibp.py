"""Tests for /ibp/ercot.

Route uses psycopg dict_row, so the fake cursor yields dicts. Two queued
result sets per request: pointer lookup (fetchone) then panel rows
(fetchall).

    docker compose run --rm api pytest /api/tests -v
"""
from __future__ import annotations

from urllib.parse import quote


def test_ibp_ercot_returns_points_with_run_id(client, fake_pool, ts_utc):
    fake_pool.cursor.queue([{'run_id': 'run-abc'}])
    fake_pool.cursor.queue([
        {'settlement_point': 'HB_HOUSTON', 'bp': 0.42},
        {'settlement_point': 'HB_NORTH',   'bp': 0.11},
    ])

    r = client.get(f'/ibp/ercot?ts={quote(ts_utc.isoformat())}')
    assert r.status_code == 200
    data = r.json()

    assert data['run_id'] == 'run-abc'
    assert data['ts'].startswith('2026-03-25T22:00')
    assert len(data['points']) == 2
    assert data['points'][0] == {'settlement_point': 'HB_HOUSTON', 'bp': 0.42}


def test_ibp_ercot_empty_points_when_hour_has_no_rows(client, fake_pool, ts_utc):
    fake_pool.cursor.queue([{'run_id': 'run-abc'}])
    fake_pool.cursor.queue([])  # promoted run has no panel row for this ts

    r = client.get(f'/ibp/ercot?ts={quote(ts_utc.isoformat())}')
    assert r.status_code == 200
    data = r.json()

    assert data['run_id'] == 'run-abc'
    assert data['points'] == []


def test_ibp_ercot_404_when_nothing_promoted(client, fake_pool, ts_utc):
    fake_pool.cursor.queue([])  # pointer row missing

    r = client.get(f'/ibp/ercot?ts={quote(ts_utc.isoformat())}')
    assert r.status_code == 404


def test_ibp_ercot_picks_up_new_run_id_after_promotion_flip(client, fake_pool, ts_utc):
    """Two sequential requests see two different run_ids — no restart."""
    # First request: pointer at run-old
    fake_pool.cursor.queue([{'run_id': 'run-old'}])
    fake_pool.cursor.queue([{'settlement_point': 'HB_HOUSTON', 'bp': 0.1}])
    r1 = client.get(f'/ibp/ercot?ts={quote(ts_utc.isoformat())}')
    assert r1.status_code == 200
    assert r1.json()['run_id'] == 'run-old'

    # Simulate a promotion flip; next request sees run-new.
    fake_pool.cursor.queue([{'run_id': 'run-new'}])
    fake_pool.cursor.queue([{'settlement_point': 'HB_HOUSTON', 'bp': 0.9}])
    r2 = client.get(f'/ibp/ercot?ts={quote(ts_utc.isoformat())}')
    assert r2.status_code == 200
    assert r2.json()['run_id'] == 'run-new'
    assert r2.json()['points'][0]['bp'] == 0.9
