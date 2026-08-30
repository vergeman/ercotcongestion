"""Forecast range HTTP route."""
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from dependencies import server_selected_run as _server_selected_run
from schemas.forecast import ForecastRangeResponse
from services.forecast_range import forecast_range
from services.time import coerce_utc

router = APIRouter()


@router.get(
    "/forecast_range",
    response_model=ForecastRangeResponse,
    summary="Per-hour deterministic forecast congestion per SP; defaults to the latest delivery day",
)
def get_forecast_range(
    run_id: str | None = Depends(_server_selected_run),
    start: datetime | None = Query(None, description="ISO-8601 UTC start (inclusive). Omit together with `end` to default to the run's latest delivery day (a UTC calendar day)."),
    end: datetime | None = Query(None, description="ISO-8601 UTC end (inclusive). Omit together with `start` to default to the run's latest delivery day (a UTC calendar day)."),
    horizon: int | None = Query(None, ge=1, le=2, description="Explicitly read one horizon track: 1 = final/t+1, 2 = preview/t+2 (0123). Omit to coalesce per day (prefer final, fall back to preview) into one continuous series. An explicit horizon with no rows for a day 404s (no fallback) — the 'what changed' view of a preserved preview."),
) -> ForecastRangeResponse:
    return forecast_range(
        run_id,
        coerce_utc(start) if start is not None else None,
        coerce_utc(end) if end is not None else None,
        horizon,
    )
