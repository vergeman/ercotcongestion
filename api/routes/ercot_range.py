"""Realized ERCOT congestion range HTTP route."""

from datetime import datetime

from fastapi import APIRouter, Query

from api.schemas.forecast import ErcotRangeResponse
from api.services.ercot_range import ercot_range
from api.services.time import validate_utc_range

router = APIRouter()


@router.get(
    "/ercot_range",
    response_model=ErcotRangeResponse,
    summary="Compact realized ERCOT congestion and SPP snapshots across a window",
)
def get_ercot_range(
    start: datetime = Query(..., description="ISO-8601 UTC start (inclusive)"),
    end: datetime = Query(..., description="ISO-8601 UTC end (inclusive)"),
) -> ErcotRangeResponse:
    start_utc, end_utc = validate_utc_range(start, end)
    return ercot_range(start_utc, end_utc)
