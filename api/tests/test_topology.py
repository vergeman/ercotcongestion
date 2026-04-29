"""Smoke test for /api/topology — patches the builder to avoid loading a real network."""
from __future__ import annotations

from unittest.mock import patch


FAKE_TOPO = {
    'buses': {
        'type': 'FeatureCollection',
        'features': [
            {
                'type': 'Feature',
                'geometry': {'type': 'Point', 'coordinates': [-97.0, 30.0]},
                'properties': {
                    'bus_id': 'B1',
                    'weather_zone': 'south_central',
                    'load_zone': 'south',
                    'voltage': 138.0,
                    'capacity_mw': 100.0,
                },
            }
        ],
    },
    'lines': {'type': 'FeatureCollection', 'features': []},
    'zones': None,
}


def test_topology_returns_geojson(client):
    with patch('topology.get_or_build_topology', return_value=FAKE_TOPO):
        r = client.get('/api/topology')
    assert r.status_code == 200
    data = r.json()
    assert data['buses']['type'] == 'FeatureCollection'
    assert len(data['buses']['features']) == 1
    props = data['buses']['features'][0]['properties']
    assert props['bus_id'] == 'B1'
    assert props['weather_zone'] == 'south_central'
    assert props['load_zone'] == 'south'


def test_topology_sets_cache_header(client):
    with patch('topology.get_or_build_topology', return_value=FAKE_TOPO):
        r = client.get('/api/topology')
    assert 'max-age' in r.headers.get('cache-control', '')

