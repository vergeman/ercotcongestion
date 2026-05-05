"""GET /api/ptdf — sparse PTDF column for a single line.

Used by the frontend's line-hover handler to highlight buses that respond
to a change on the hovered line. The full PTDF matrix is large
(~2700 lines x ~2750 buses) and topology-static, so we cache it in-memory
on the first request (see services/ptdf_service.py).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from services.ptdf_service import get_line_ptdf_column

router = APIRouter()


@router.get(
    '/ptdf',
    summary='Sparse PTDF column for a line',
    description=(
        'Returns the PTDF column for one line: each bus paired with its '
        'sensitivity (signed). Sparsified by absolute threshold and capped by '
        'top-K. Topology-static and cacheable forever.'
    ),
)
def ptdf(
    line_id: str = Query(..., description='Line id (matches topology.lines features).'),
    threshold: float = Query(0.05, ge=0.0, le=1.0, description='Drop |PTDF| below this.'),
    top: int = Query(100, ge=1, le=500, description='Cap returned buses to top-K by |PTDF|.'),
) -> JSONResponse:
    result = get_line_ptdf_column(line_id, threshold=threshold, max_buses=top)
    if result is None:
        raise HTTPException(status_code=404, detail=f'Unknown line_id: {line_id}')
    return JSONResponse(
        content=result,
        # Topology-static — safe to cache for the session.
        headers={'Cache-Control': 'public, max-age=86400'},
    )
