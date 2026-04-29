"""GET /api/topology — static GeoJSON of buses, lines, zones."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from services.topology_builder import get_or_build_topology

router = APIRouter()


@router.get(
    '/topology',
    summary='Static network topology',
    description='Returns FeatureCollections for buses, lines, and (when available) zone polygons. Cached on disk; rebuild by deleting TOPOLOGY_CACHE.',
)
def topology() -> JSONResponse:
    topo = get_or_build_topology()
    # Long max-age — topology only changes when we regenerate it.
    return JSONResponse(
        content=topo,
        headers={'Cache-Control': 'public, max-age=86400'},
    )
