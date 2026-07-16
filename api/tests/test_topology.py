"""Smoke test for /topology — patches the builder to avoid reading real CSVs."""
from __future__ import annotations

from unittest.mock import patch

from services import topology_builder


FAKE_TOPO = {
    'settlement_points': {
        'type': 'FeatureCollection',
        'features': [
            {
                'type': 'Feature',
                'geometry': {'type': 'Point', 'coordinates': [-97.0, 30.0]},
                'properties': {
                    'sp_id': 'LZ_SOUTH',
                    'sp_type': 'LZ',
                    'load_zone': 'south',
                    'capacity_mw': 0.0,
                },
            }
        ],
    },
}


def test_topology_returns_settlement_points_only(client):
    with patch('topology.get_or_build_topology', return_value=FAKE_TOPO):
        r = client.get('/topology')
    assert r.status_code == 200
    data = r.json()
    assert set(data.keys()) == {'settlement_points'}
    assert 'buses' not in data
    assert 'lines' not in data
    sps = data['settlement_points']
    assert sps['type'] == 'FeatureCollection'
    assert len(sps['features']) == 1
    props = sps['features'][0]['properties']
    assert set(props) == {'sp_id', 'sp_type', 'load_zone', 'capacity_mw'}
    assert props['sp_id'] == 'LZ_SOUTH'
    assert props['load_zone'] == 'south'
    assert props['capacity_mw'] == 0.0


def test_topology_sets_cache_header(client):
    with patch('topology.get_or_build_topology', return_value=FAKE_TOPO):
        r = client.get('/topology')
    assert 'max-age' in r.headers.get('cache-control', '')


def test_stale_legacy_cache_is_not_current():
    """A cache carrying buses/lines (legacy schema) rebuilds on first hit."""
    legacy = {
        'buses': {'type': 'FeatureCollection', 'features': []},
        'lines': {'type': 'FeatureCollection', 'features': []},
        'settlement_points': {'type': 'FeatureCollection', 'features': []},
    }
    assert topology_builder._cache_is_current(legacy) is False


def test_sp_cache_without_capacity_is_not_current():
    """An SP-only cache predating the capacity_mw field rebuilds."""
    stale = {
        'settlement_points': {
            'type': 'FeatureCollection',
            'features': [
                {'type': 'Feature', 'properties': {'sp_id': 'X', 'load_zone': None}},
            ],
        },
    }
    assert topology_builder._cache_is_current(stale) is False


def test_current_sp_cache_is_current():
    assert topology_builder._cache_is_current(FAKE_TOPO) is True
