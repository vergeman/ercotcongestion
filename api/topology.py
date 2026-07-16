"""GET /api/topology — static GeoJSON of geocoded settlement points."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from services.topology_builder import get_or_build_topology

router = APIRouter()


@router.get(
    '/topology',
    summary='Static settlement-point topology',
    description='Returns a FeatureCollection of geocoded ERCOT settlement points (sp_id, sp_type, load_zone, capacity_mw). Cached on disk; rebuild by deleting TOPOLOGY_CACHE.',
)
def topology() -> JSONResponse:
    topo = get_or_build_topology()
    # Long max-age — topology only changes when we regenerate it.
    return JSONResponse(
        content=topo,
        headers={'Cache-Control': 'public, max-age=86400'},
    )
