"""End-to-end smoke tests against a real Postgres.

Skipped by default; run with:

    docker compose run --rm -e RUN_INTEGRATION=1 api pytest /api/tests/test_integration.py -v

Requires Migration A applied and at least one recomputed snapshot
(bus_snapshots.modeled_congestion + basis populated for some interval_ts).
"""
from __future__ import annotations

from datetime import timedelta
from urllib.parse import quote

import pytest

import db as db_module


pytestmark = pytest.mark.integration


NULL_ROW_BUS_ID = '__integration_null_probe__'


def _latest_recomputed_ts():
    """Most recent interval_ts with both modeled_congestion and basis populated."""
    pool = db_module.get_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT bs.interval_ts
            FROM bus_snapshots bs
            JOIN snapshot_meta sm ON sm.interval_ts = bs.interval_ts
            WHERE bs.modeled_congestion IS NOT NULL
              AND bs.basis IS NOT NULL
              AND sm.status = 'ok'
            ORDER BY bs.interval_ts DESC
            LIMIT 1
            """
        )
        row = cur.fetchone()
    if row is None:
        pytest.skip('no recomputed snapshot in DB')
    return row[0]


def test_state_endpoint(real_client):
    ts = _latest_recomputed_ts()
    r = real_client.get(f'/state?t={quote(ts.isoformat())}')
    assert r.status_code == 200
    body = r.json()
    assert body['meta']['status'] == 'ok'
    assert body['buses'], 'expected at least one bus row'
    for bus in body['buses']:
        assert 'modeled_congestion' in bus
        assert 'binding_proximity' in bus
        assert 'fragility' not in bus


def test_state_range_endpoint(real_client):
    ts = _latest_recomputed_ts()
    start = quote(ts.isoformat())
    end = quote((ts + timedelta(hours=1)).isoformat())
    r = real_client.get(f'/state_range?start={start}&end={end}')
    assert r.status_code == 200
    body = r.json()
    assert body['count'] >= 1
    for entry in body['entries']:
        for bus in entry['buses']:
            assert 'modeled_congestion' in bus
            assert 'fragility' not in bus


def test_validation_endpoint(real_client):
    ts = _latest_recomputed_ts()
    start = quote(ts.isoformat())
    end = quote((ts + timedelta(hours=1)).isoformat())
    r = real_client.get(f'/validation?start={start}&end={end}')
    assert r.status_code == 200
    body = r.json()
    assert body['n_observations'] > 0
    assert body['overall']['rho'] is not None
    for pt in body['scatter']:
        assert 'modeled_congestion' in pt
        assert 'basis' in pt
        assert 'abs_basis' in pt
    assert 'sign_agreement_overall' in body
    assert 'sign_agreement_congested' in body
    assert 'fragility' not in r.text


def test_validation_tolerates_null_modeled_congestion(real_client):
    """Insert a bus_snapshots row with NULL modeled_congestion and confirm
    the endpoint's IS NOT NULL filter excludes it without erroring."""
    ts = _latest_recomputed_ts()
    pool = db_module.get_pool()
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bus_snapshots (interval_ts, bus_id, modeled_congestion, basis, lmp)
            VALUES (%s, %s, NULL, 42.0, 25.0)
            ON CONFLICT (interval_ts, bus_id) DO UPDATE
              SET modeled_congestion = NULL, basis = 42.0
            """,
            (ts, NULL_ROW_BUS_ID),
        )
    try:
        start = quote(ts.isoformat())
        end = quote((ts + timedelta(hours=1)).isoformat())
        r = real_client.get(f'/validation?start={start}&end={end}')
        assert r.status_code == 200
        body = r.json()
        # Probe row must not appear in scatter (filtered by SQL).
        for pt in body['scatter']:
            assert pt['basis'] != 42.0 or pt['modeled_congestion'] is not None
    finally:
        with pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                'DELETE FROM bus_snapshots WHERE interval_ts = %s AND bus_id = %s',
                (ts, NULL_ROW_BUS_ID),
            )
