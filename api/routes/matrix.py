"""HTTP adapter for the bounded causal Matrix frame."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from api.db import get_pool
from api.schemas.matrix import MatrixFrame
from api.services.matrix.frame import build_frame
from api.services.matrix.models import MatrixFrameRequest
from api.services.matrix.repository import MatrixRepository
from api.services.matrix.selection import DEFAULT_ROW_LIMIT, MAX_COLUMN_LIMIT, MAX_PINNED_ITEMS, MAX_ROW_LIMIT
from api.services.settlement_points import metadata as settlement_point_metadata
from api.services.time import coerce_utc


router = APIRouter(prefix="/matrix")
DEFAULT_COLUMN_LIMIT = 40
MAX_SEARCH_LENGTH = 64


def get_settlement_point_metadata() -> dict[str, tuple[str | None, str | None]]:
    """FastAPI dependency and explicit test seam for Matrix node metadata."""
    return settlement_point_metadata()


def _bounded_values(values: list[str], *, name: str) -> list[str]:
    normalized: list[str] = []
    for value in values:
        value = value.strip()
        if value and value not in normalized:
            normalized.append(value)
    if len(normalized) > MAX_PINNED_ITEMS:
        raise HTTPException(status_code=422, detail=f"{name} supports at most {MAX_PINNED_ITEMS} values.")
    return normalized


def _bounded_search(value: str | None, *, name: str) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) > MAX_SEARCH_LENGTH:
        raise HTTPException(status_code=422, detail=f"{name} must be at most {MAX_SEARCH_LENGTH} characters.")
    return value.casefold() or None


@router.get("/frame", response_model=MatrixFrame, summary="Bounded causal SF matrix frame")
def get_matrix_frame(
    interval_ts: datetime = Query(..., description="Delivery interval in ISO-8601 UTC."),
    row_limit: int = Query(DEFAULT_ROW_LIMIT, ge=1, le=MAX_ROW_LIMIT),
    column_limit: int = Query(DEFAULT_COLUMN_LIMIT, ge=1, le=MAX_COLUMN_LIMIT),
    row_preset: str = Query("top30", pattern="^(top30|top100|pinned)$"),
    constraint_type: str | None = Query(None, pattern="^(gtc|transmission|radial)$"),
    constraint_search: str | None = Query(None),
    settlement_point_search: str | None = Query(None),
    pinned_constraint: list[str] = Query(default=[]),
    pinned_settlement_point: list[str] = Query(default=[]),
    peek_constraint: str | None = Query(None, description="Force-include one previewed constraint as a row, beyond the pin cap (the working-set top-row preview)."),
    peek_settlement_point: str | None = Query(None, description="Force-include one previewed settlement point as a column, beyond the pin cap."),
    column_set: str = Query("core", pattern="^(core|anchors|pinned|core_pinned|default_anchors)$", description="Bounded named column selection."),
    orientation: str = Query("constraints", pattern="^(constraints|nodes)$", description="Which axis gets the primary ranked/searched list treatment."),
    row_order: str = Query("contribution", pattern="^(contribution|cursor_mu|anchor_contribution)$", description="Constraint row selection order."),
    metadata: dict[str, tuple[str | None, str | None]] = Depends(get_settlement_point_metadata),
) -> MatrixFrame:
    request = MatrixFrameRequest(
        interval_ts=coerce_utc(interval_ts), row_limit=row_limit, column_limit=column_limit,
        row_preset=row_preset, constraint_type=constraint_type,
        constraint_search=_bounded_search(constraint_search, name="constraint_search"),
        settlement_point_search=_bounded_search(settlement_point_search, name="settlement_point_search"),
        pinned_constraints=_bounded_values(pinned_constraint, name="pinned_constraint"),
        pinned_settlement_points=_bounded_values(pinned_settlement_point, name="pinned_settlement_point"),
        peek_constraint=peek_constraint, peek_settlement_point=peek_settlement_point,
        column_set=column_set, orientation=orientation, row_order=row_order,
    )
    return build_frame(request, MatrixRepository(get_pool()), metadata)
