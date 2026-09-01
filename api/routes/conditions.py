"""Conditions panel HTTP route."""

from datetime import datetime

from fastapi import APIRouter, Query

from api.schemas.conditions import ConditionsRangeResponse
from api.services.conditions import conditions_range
from api.services.time import coerce_utc

router = APIRouter()


@router.get(
    "/conditions_range",
    response_model=ConditionsRangeResponse,
    summary="Per-hour Load / Wind / Solar / Outages, merged",
)
def get_conditions_range(
    start: datetime = Query(..., description="ISO-8601 UTC start (inclusive)"),
    end: datetime = Query(..., description="ISO-8601 UTC end (inclusive)"),
) -> ConditionsRangeResponse:
    return conditions_range(coerce_utc(start), coerce_utc(end))
