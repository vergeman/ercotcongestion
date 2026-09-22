"""Forecast range HTTP route."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from api.dependencies import server_selected_run as _server_selected_run
from api.schemas.forecast import ForecastRangeResponse
from api.services.forecast_range import forecast_range
from api.services.time import validate_optional_utc_range

router = APIRouter()


@router.get(
    "/forecast_range",
    response_model=ForecastRangeResponse,
    summary="Per-hour deterministic forecast congestion per SP; defaults to the latest delivery day",
)
def get_forecast_range(
    run_id: str | None = Depends(_server_selected_run),
    start: datetime | None = Query(
        None,
        description="ISO-8601 UTC start (inclusive). Omit together with `end` to default to the run's latest delivery day (a UTC calendar day).",
    ),
    end: datetime | None = Query(
        None,
        description="ISO-8601 UTC end (inclusive). Omit together with `start` to default to the run's latest delivery day (a UTC calendar day).",
    ),
    horizon: int | None = Query(
        None,
        ge=1,
        le=2,
        description="Explicitly read one horizon track: 1 = final/t+1, 2 = preview/t+2. No rows 404.",
    ),
) -> ForecastRangeResponse:
    start_utc, end_utc = validate_optional_utc_range(start, end)
    return forecast_range(
        run_id,
        start_utc,
        end_utc,
        horizon,
    )
