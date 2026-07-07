"""Tests for /ibp/ercot and /ibp/ercot_range.

Routes use psycopg dict_row, so the fake cursor yields dicts. Two queued
result sets per request: pointer lookup (fetchone) then panel rows
(fetchall).

    docker compose run --rm api pytest /api/tests -v
"""
from __future__ import annotations

from datetime import datetime, timezone
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


def test_ibp_ercot_range_returns_grouped_entries_with_run_id(client, fake_pool):
    start = datetime(2026, 3, 25, 22, 0, tzinfo=timezone.utc)
    end   = datetime(2026, 3, 25, 23, 0, tzinfo=timezone.utc)
    fake_pool.cursor.queue([{'run_id': 'run-abc'}])
    fake_pool.cursor.queue([
        {'ts': start, 'settlement_point': 'HB_HOUSTON', 'bp': 0.42},
        {'ts': start, 'settlement_point': 'HB_NORTH',   'bp': 0.11},
        {'ts': end,   'settlement_point': 'HB_HOUSTON', 'bp': 0.55},
    ])

    r = client.get(f'/ibp/ercot_range?start={quote(start.isoformat())}&end={quote(end.isoformat())}')
    assert r.status_code == 200
    data = r.json()

    assert data['run_id'] == 'run-abc'
    assert data['count'] == 2
    assert len(data['entries']) == 2

    e0 = data['entries'][0]
    assert e0['interval_ts'].startswith('2026-03-25T22:00')
    assert len(e0['points']) == 2
    assert {p['settlement_point'] for p in e0['points']} == {'HB_HOUSTON', 'HB_NORTH'}

    e1 = data['entries'][1]
    assert e1['interval_ts'].startswith('2026-03-25T23:00')
    assert e1['points'] == [{'settlement_point': 'HB_HOUSTON', 'bp': 0.55}]


def test_ibp_ercot_range_503_when_nothing_promoted(client, fake_pool):
    start = datetime(2026, 3, 25, 22, 0, tzinfo=timezone.utc)
    end   = datetime(2026, 3, 25, 23, 0, tzinfo=timezone.utc)
    fake_pool.cursor.queue([])  # pointer row missing

    r = client.get(f'/ibp/ercot_range?start={quote(start.isoformat())}&end={quote(end.isoformat())}')
    assert r.status_code == 503
    assert 'no implied_binding_proximity run promoted' in r.json()['detail']


def test_ibp_ercot_range_503_when_pointer_exists_but_window_empty(client, fake_pool):
    start = datetime(2026, 3, 25, 22, 0, tzinfo=timezone.utc)
    end   = datetime(2026, 3, 25, 23, 0, tzinfo=timezone.utc)
    fake_pool.cursor.queue([{'run_id': 'run-abc'}])
    fake_pool.cursor.queue([])  # promoted run has no rows in the window

    r = client.get(f'/ibp/ercot_range?start={quote(start.isoformat())}&end={quote(end.isoformat())}')
    assert r.status_code == 503
    assert 'no implied_binding_proximity rows in window' in r.json()['detail']


def test_ibp_ercot_range_synthesizes_empty_entry_for_missing_hour(client, fake_pool):
    start = datetime(2026, 3, 25, 22, 0, tzinfo=timezone.utc)
    end   = datetime(2026, 3, 26, 0, 0, tzinfo=timezone.utc)
    fake_pool.cursor.queue([{'run_id': 'run-abc'}])
    # Only the first and last hour have rows; the middle hour is missing.
    fake_pool.cursor.queue([
        {'ts': start, 'settlement_point': 'HB_HOUSTON', 'bp': 0.42},
        {'ts': end,   'settlement_point': 'HB_HOUSTON', 'bp': 0.55},
    ])

    r = client.get(f'/ibp/ercot_range?start={quote(start.isoformat())}&end={quote(end.isoformat())}')
    assert r.status_code == 200
    data = r.json()

    assert data['count'] == 3
    assert len(data['entries']) == 3
    assert data['entries'][0]['interval_ts'].startswith('2026-03-25T22:00')
    assert len(data['entries'][0]['points']) == 1

    # Middle hour synthesized empty.
    assert data['entries'][1]['interval_ts'].startswith('2026-03-25T23:00')
    assert data['entries'][1]['points'] == []

    assert data['entries'][2]['interval_ts'].startswith('2026-03-26T00:00')
    assert len(data['entries'][2]['points']) == 1


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
