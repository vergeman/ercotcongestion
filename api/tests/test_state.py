"""Tests for /state and /state_range.

Routes use psycopg's dict_row factory, so the fake cursor must yield dicts.

docker compose run --rm api pytest /api/tests -v

"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote


def _meta_row(ts: datetime, status: str = 'ok') -> dict:
    """Build a meta row dict matching SnapshotMeta field names."""
    return {
        'interval_ts': ts,
        'status': status,
        'objective_cost': 1234.5,
        'dam_system_lambda': 42.75,
        'total_load_mw': 50000.0,
        'total_gen_mw': 50100.0,
        'n_binding_lines': 3,
        'lmp_min': -10.0,
        'lmp_mean': 25.0,
        'lmp_max': 80.0,
        'modeled_congestion_total': 100.5,
        'modeled_congestion_abs_total': 150.5,
        'modeled_congestion_top10_share': 0.42,
        'binding_proximity_max': 0.95,
        'binding_proximity_p95': 0.80,
        'binding_lines': [{'line': 'L1', 'shadow_price': 5.0}],
        'top_contingencies': [{'line': 'L2', 'stress': 0.7}],
        'dispatch_by_carrier': {'gas': 30000.0, 'wind': 10000.0},
        'wind_factor_by_region': {'panhandle': 0.3},
        'solar_factor_by_region': {'south': 0.6},
        'outage_posting_ts': ts - timedelta(minutes=5),
        'error_message': None,
    }


def test_state_returns_meta_and_buses(client, fake_pool, ts_utc):
    fake_pool.cursor.queue([_meta_row(ts_utc)])
    fake_pool.cursor.queue([
        {'bus_id': 'B1', 'modeled_congestion': 0.5, 'binding_proximity': 0.7, 'lmp': 25.0},
        {'bus_id': 'B2', 'modeled_congestion': 0.2, 'binding_proximity': 0.3, 'lmp': 24.0},
    ])

    r = client.get(f'/state?t={quote(ts_utc.isoformat())}')
    assert r.status_code == 200
    data = r.json()

    assert data['interval_ts'].startswith('2026-03-25T22:00')
    assert data['meta']['status'] == 'ok'
    assert data['meta']['n_binding_lines'] == 3
    assert data['meta']['dam_system_lambda'] == 42.75
    assert len(data['buses']) == 2
    assert data['buses'][0]['bus_id'] == 'B1'

    # Schema regression guard: new metric fields present.
    for bus in data['buses']:
        assert 'modeled_congestion' in bus
        assert 'binding_proximity' in bus


def test_state_404_when_missing(client, fake_pool, ts_utc):
    fake_pool.cursor.queue([])  # no meta row
    r = client.get(f'/state?t={quote(ts_utc.isoformat())}')
    assert r.status_code == 404


def test_state_range_groups_buses_per_snapshot(client, fake_pool, ts_utc):
    ts2 = ts_utc + timedelta(hours=1)
    fake_pool.cursor.queue([_meta_row(ts_utc), _meta_row(ts2)])
    fake_pool.cursor.queue([
        {'interval_ts': ts_utc, 'bus_id': 'B1', 'modeled_congestion': 0.5, 'binding_proximity': 0.7, 'lmp': 25.0},
        {'interval_ts': ts_utc, 'bus_id': 'B2', 'modeled_congestion': 0.2, 'binding_proximity': 0.3, 'lmp': 24.0},
        {'interval_ts': ts2,    'bus_id': 'B1', 'modeled_congestion': 0.6, 'binding_proximity': 0.8, 'lmp': 26.0},
        {'interval_ts': ts2,    'bus_id': 'B2', 'modeled_congestion': 0.3, 'binding_proximity': 0.4, 'lmp': 25.5},
    ])

    start = quote(ts_utc.isoformat())
    end = quote((ts_utc + timedelta(hours=2)).isoformat())
    r = client.get(f'/state_range?start={start}&end={end}')
    assert r.status_code == 200
    data = r.json()

    assert data['count'] == 2
    assert len(data['entries']) == 2
    assert data['entries'][0]['meta']['dam_system_lambda'] == 42.75
    assert data['entries'][1]['meta']['dam_system_lambda'] == 42.75
    assert len(data['entries'][0]['buses']) == 2
    assert len(data['entries'][1]['buses']) == 2

    # Schema regression guard: new metric fields present.
    for entry in data['entries']:
        for bus in entry['buses']:
            assert 'modeled_congestion' in bus
            assert 'binding_proximity' in bus


def test_state_range_rejects_inverted_window(client, ts_utc):
    s = quote(ts_utc.isoformat())
    e = quote((ts_utc - timedelta(hours=1)).isoformat())
    r = client.get(f'/state_range?start={s}&end={e}')
    assert r.status_code == 400


def test_state_range_rejects_oversize_window(client, ts_utc):
    s = quote(ts_utc.isoformat())
    e = quote((ts_utc + timedelta(days=30)).isoformat())
    r = client.get(f'/state_range?start={s}&end={e}')
    assert r.status_code == 400
