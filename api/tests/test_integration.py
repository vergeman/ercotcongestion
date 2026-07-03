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


# /validation is now artifact-driven (0047 scorecard) rather than
# bus_snapshots-driven; unit coverage lives in test_validation.py.
