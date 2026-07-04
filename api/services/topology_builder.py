"""Build static topology GeoJSON from the PyPSA network and CSV reference data.

Output shape (cached as JSON to TOPOLOGY_CACHE):

  {
    "buses": { "type": "FeatureCollection", "features": [...] },
    "lines": { "type": "FeatureCollection", "features": [...] },
    "zones": null   # placeholder; zone polygons land here when sourced
  }

Bus features carry: bus_id, weather_zone, load_zone, voltage, capacity_mw.
Line features carry: line_id, bus0, bus1, s_nom, length (if present).

bus_zones.csv (BUS_ZONES_PATH) is produced by scripts/assign_bus_weather_load_zones.py
and has columns: name, lat, lon, ercot_weather_zone, ercot_load_zone.
We expose them in the GeoJSON as `weather_zone` and `load_zone` for the frontend.

Idempotent: regenerating from the same inputs produces an identical file.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import pandas as pd

from config import (
    BUS_WEATHER_LOAD_ZONES_CSV,
    GENERATOR_MATCHES_ENRICHED_CSV,
    NETWORK_NC,
    TOPOLOGY_CACHE
)
from shared.settings import settings

log = logging.getLogger(__name__)


def build_topology() -> dict[str, Any]:
    """Build topology dict from PyPSA network + CSVs. Does not write to disk."""
    import pypsa  # heavy import; only when actually building
    log.info("Loading network from %s", NETWORK_NC)
    n = pypsa.Network(NETWORK_NC)

    bus_zones = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    bus_zones['name'] = bus_zones['name'].astype(str)

    # Required columns: name, ercot_weather_zone, ercot_load_zone
    # Produced by scripts/assign_bus_weather_load_zones.py
    required = {'name', 'ercot_weather_zone', 'ercot_load_zone'}
    missing = required - set(bus_zones.columns)
    if missing:
        raise ValueError(
            f"{BUS_WEATHER_LOAD_ZONES_CSV} missing required columns: {sorted(missing)}. "
            f"Got: {list(bus_zones.columns)}. "
            f"Regenerate via scripts/assign_bus_weather_load_zones.py."
        )

    # Normalize zone names: lowercase, underscores. Keeps the frontend and
    # downstream code from worrying about 'North Central' vs 'north_central'.
    for col in ('ercot_weather_zone', 'ercot_load_zone'):
        bus_zones[col] = (
            bus_zones[col].astype(str).str.lower().str.replace(' ', '_')
        )

    weather_lookup = dict(zip(bus_zones['name'], bus_zones['ercot_weather_zone']))
    load_lookup    = dict(zip(bus_zones['name'], bus_zones['ercot_load_zone']))

    # Generator nameplate per bus (used for sizing in the UI)
    try:
        gen = pd.read_csv(GENERATOR_MATCHES_ENRICHED_CSV)
        gen['bus'] = gen['bus'].astype(str)
        bus_capacity = gen.groupby('bus')['capacity_mw'].sum().to_dict()
    except FileNotFoundError:
        log.warning("gen_enriched not found; bus capacity_mw will be 0")
        bus_capacity = {}

    bus_cluster = _load_bus_cluster_labels()

    buses_fc = _buses_feature_collection(
        n, weather_lookup, load_lookup, bus_capacity, bus_cluster,
    )
    lines_fc = _lines_feature_collection(n)
    sps_fc = _settlement_points_feature_collection()
    zones_fc = _load_zone_polygons()

    return {
        'buses': buses_fc,
        'lines': lines_fc,
        'settlement_points': sps_fc,
        'zones': zones_fc,
    }


def _load_bus_cluster_labels() -> dict[str, int]:
    """Return {bus_id: cluster_id} for the active run's clustering artifact.

    Soft-fails to {} when the run/algo/k combination has no labels file —
    the frontend then treats every bus as unclustered.
    """
    import numpy as np

    labels_path = (
        f"{settings.compute_runs_dir}/{settings.active_run_id}/clustering/"
        f"cluster_labels_{settings.active_cluster_algo}_k{settings.active_cluster_k}.npz"
    )
    if not os.path.exists(labels_path):
        log.warning("bus cluster labels not found at %s; cluster_id will be null", labels_path)
        return {}
    with np.load(labels_path, allow_pickle=False) as z:
        return {str(b): int(c) for b, c in zip(z['bus_id'], z['cluster_id'])}


def _settlement_points_feature_collection() -> dict[str, Any]:
    """Return SP points as GeoJSON. Rows missing lat/lon are dropped."""
    try:
        df = pd.read_csv(settings.settlement_points_geocoded_csv)
    except FileNotFoundError:
        log.warning("settlement_points geocoded csv missing; ERCOT pane will be empty")
        return {'type': 'FeatureCollection', 'features': []}
    df = df.dropna(subset=['lat', 'lon'])
    features = []
    for _, row in df.iterrows():
        sp_id = str(row['settlement_point'])
        features.append({
            'type': 'Feature',
            'geometry': {
                'type': 'Point',
                'coordinates': [float(row['lon']), float(row['lat'])],
            },
            'properties': {
                'sp_id': sp_id,
                'sp_type': str(row.get('sp_type') or ''),
            },
        })
    return {'type': 'FeatureCollection', 'features': features}


def _load_zone_polygons() -> dict[str, Any] | None:
    """Return cluster polygon FeatureCollection, or None if absent.

    File convention mirrors the bus cluster labels naming: the polygons
    live at ``zones_<active_cluster_algo>_k<k>.geojson`` inside the run's
    clustering directory. A missing file yields ``None`` — the frontend
    then keeps its polygon-free rendering path.
    """
    polygons_path = (
        f"{settings.compute_runs_dir}/{settings.active_run_id}/clustering/"
        f"zones_{settings.active_cluster_algo}_k{settings.active_cluster_k}.geojson"
    )
    if not os.path.exists(polygons_path):
        log.info("zone polygons not found at %s; topology zones = null", polygons_path)
        return None
    with open(polygons_path) as f:
        return json.load(f)


def _cache_is_current(topo: dict[str, Any]) -> bool:
    """Detect stale caches from older schema revisions.

    A cache without `settlement_points` at top level, or bus features without
    `cluster_id`, was written before 0048's S3.2/S3.4 schema. Rebuild instead
    of silently serving a payload the frontend can't use.
    """
    if 'settlement_points' not in topo:
        return False
    features = topo.get('buses', {}).get('features', [])
    if features and 'cluster_id' not in features[0].get('properties', {}):
        return False
    return True


def get_or_build_topology(force: bool = False) -> dict[str, Any]:
    """Return cached topology dict, building and writing the cache if missing."""
    if not force and os.path.exists(TOPOLOGY_CACHE):
        with open(TOPOLOGY_CACHE) as f:
            topo = json.load(f)
        if _cache_is_current(topo):
            log.info("Topology cache hit: %s", TOPOLOGY_CACHE)
            return topo
        log.info("Topology cache stale; rebuilding: %s", TOPOLOGY_CACHE)

    topo = build_topology()
    os.makedirs(os.path.dirname(TOPOLOGY_CACHE), exist_ok=True)
    tmp = TOPOLOGY_CACHE + '.tmp'
    print(tmp)
    with open(tmp, 'w') as f:
        json.dump(topo, f)
    os.replace(tmp, TOPOLOGY_CACHE)
    log.info("Wrote topology cache: %s", TOPOLOGY_CACHE)
    return topo


# ---------------------------------------------------------------------------
# Feature collection builders
# ---------------------------------------------------------------------------

def _buses_feature_collection(
    n,  # pypsa.Network — not annotated to avoid the import
    weather_lookup: dict[str, str],
    load_lookup: dict[str, str],
    bus_capacity: dict[str, float],
    bus_cluster: dict[str, int],
) -> dict[str, Any]:
    features = []
    for bus_id, row in n.buses.iterrows():
        x, y = float(row.get('x', 0.0)), float(row.get('y', 0.0))
        if x == 0.0 and y == 0.0:
            continue  # buses without coords are useless on a map
        bus_id_str = str(bus_id)
        features.append({
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [x, y]},
            'properties': {
                'bus_id': bus_id_str,
                'weather_zone': weather_lookup.get(bus_id_str),
                'load_zone':    load_lookup.get(bus_id_str),
                'voltage': float(row['v_nom']) if 'v_nom' in row and pd.notna(row['v_nom']) else None,
                'capacity_mw': float(bus_capacity.get(bus_id_str, 0.0)),
                'cluster_id':  bus_cluster.get(bus_id_str),
            },
        })
    return {'type': 'FeatureCollection', 'features': features}


def _lines_feature_collection(n) -> dict[str, Any]:
    features = []
    bus_xy = n.buses[['x', 'y']]
    for line_id, row in n.lines.iterrows():
        b0, b1 = str(row['bus0']), str(row['bus1'])
        if b0 not in bus_xy.index or b1 not in bus_xy.index:
            continue
        x0, y0 = float(bus_xy.at[b0, 'x']), float(bus_xy.at[b0, 'y'])
        x1, y1 = float(bus_xy.at[b1, 'x']), float(bus_xy.at[b1, 'y'])
        if (x0, y0) == (0.0, 0.0) or (x1, y1) == (0.0, 0.0):
            continue
        features.append({
            'type': 'Feature',
            'geometry': {'type': 'LineString', 'coordinates': [[x0, y0], [x1, y1]]},
            'properties': {
                'line_id': str(line_id),
                'bus0': b0,
                'bus1': b1,
                's_nom': float(row['s_nom']) if pd.notna(row.get('s_nom')) else None,
                'length': float(row['length']) if pd.notna(row.get('length')) else None,
            },
        })
    return {'type': 'FeatureCollection', 'features': features}


if __name__ == '__main__':
    """CLI: rebuild and write the topology cache."""
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    topo = get_or_build_topology(force=True)
    print(
        f"buses={len(topo['buses']['features'])} "
        f"lines={len(topo['lines']['features'])}"
    )
