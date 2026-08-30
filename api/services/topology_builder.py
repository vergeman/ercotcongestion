"""Build static topology GeoJSON from the geocoded settlement points.

Output shape (cached as JSON to TOPOLOGY_CACHE):

  {
    "settlement_points": { "type": "FeatureCollection", "features": [...] }
  }

SP features carry: sp_id, sp_type, load_zone, capacity_mw.

settlement_points_geocoded_csv has columns: settlement_point, lat, lon,
sp_type, load_zone, matched_capacity_mw. `capacity_mw` comes from
`matched_capacity_mw` and is used for node sizing in the UI.

Idempotent: regenerating from the same inputs produces an identical file.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import pandas as pd

from api.config import TOPOLOGY_CACHE
from shared.settings import settings

log = logging.getLogger(__name__)


def build_topology() -> dict[str, Any]:
    """Build topology dict from the geocoded SPs. Does not write to disk."""
    return {'settlement_points': _settlement_points_feature_collection()}


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
        raw_load_zone = row.get('load_zone')
        load_zone = None if pd.isna(raw_load_zone) else str(raw_load_zone)
        cap = row.get('matched_capacity_mw')
        features.append({
            'type': 'Feature',
            'geometry': {
                'type': 'Point',
                'coordinates': [float(row['lon']), float(row['lat'])],
            },
            'properties': {
                'sp_id': sp_id,
                'sp_type': str(row.get('sp_type') or ''),
                'load_zone': load_zone,
                'capacity_mw': float(cap) if pd.notna(cap) else 0.0,
            },
        })
    return {'type': 'FeatureCollection', 'features': features}


def _cache_is_current(topo: dict[str, Any]) -> bool:
    """Detect stale caches from older schema revisions.

    A cache carrying `buses`/`lines` at top level is the legacy synthetic-grid
    schema (pre-0090). A cache whose SP features lack `capacity_mw` predates the
    0090 SP-only rewrite. Either case rebuilds instead of serving a payload the
    frontend can't use.
    """
    if 'buses' in topo or 'lines' in topo:
        return False
    if 'settlement_points' not in topo:
        return False
    sp_features = topo.get('settlement_points', {}).get('features', [])
    if sp_features and 'capacity_mw' not in sp_features[0].get('properties', {}):
        return False
    return True


def get_or_build_topology(force: bool = False) -> dict[str, Any]:
    """Return cached topology dict, building and writing the cache if missing."""
    if not force and os.path.exists(TOPOLOGY_CACHE):
        with open(TOPOLOGY_CACHE) as f:
            topo = json.load(f)
        source_is_newer = (
            os.path.exists(settings.settlement_points_geocoded_csv)
            and os.path.getmtime(settings.settlement_points_geocoded_csv) > os.path.getmtime(TOPOLOGY_CACHE)
        )
        if _cache_is_current(topo) and not source_is_newer:
            log.info("Topology cache hit: %s", TOPOLOGY_CACHE)
            return topo
        log.info("Topology cache stale or source updated; rebuilding: %s", TOPOLOGY_CACHE)

    topo = build_topology()
    os.makedirs(os.path.dirname(TOPOLOGY_CACHE), exist_ok=True)
    # Unique tmp per rebuild so concurrent requests don't clobber each other's
    # tmp file — the final os.replace still atomically publishes.
    tmp = f"{TOPOLOGY_CACHE}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    with open(tmp, 'w') as f:
        json.dump(topo, f)
    os.replace(tmp, TOPOLOGY_CACHE)
    log.info("Wrote topology cache: %s", TOPOLOGY_CACHE)
    return topo


if __name__ == '__main__':
    """CLI: rebuild and write the topology cache."""
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    topo = get_or_build_topology(force=True)
    print(f"settlement_points={len(topo['settlement_points']['features'])}")
