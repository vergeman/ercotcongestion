"""Analysis hero endpoints."""

from datetime import date

from fastapi import APIRouter, Depends, Query

from api.dependencies import server_selected_run as _server_selected_run
from api.services.analysis.features import hero as hero_service
from api.schemas.analysis import (
    HeroAvailableResponse,
    HeroLatestResponse,
    HeroUnavailableAtHorizonResponse,
    HeroUnavailableResponse,
)

router = APIRouter(prefix="/analysis")
@router.get(
    "/hero/latest",
    response_model=HeroLatestResponse,
    summary="Newest v6 Brief delivery day with a published artifact",
)
def get_hero_latest(
    run_id: str | None = Depends(_server_selected_run),
) -> HeroLatestResponse:
    return hero_service.latest(run_id)


@router.get(
    "/hero",
    response_model=HeroAvailableResponse
    | HeroUnavailableResponse
    | HeroUnavailableAtHorizonResponse,
    summary="Server-computed v6 daily-brief hero",
)
def get_hero(
    delivery_date: date | None = Query(None, description="ERCOT delivery day."),
    run_id: str | None = Depends(_server_selected_run),
    horizon: int | None = Query(None, ge=1, le=2, description="Artifact track; final preferred."),
    *,
    day: date | None = Query(None, alias="date", deprecated=True, description="Deprecated alias for delivery_date."),
) -> HeroAvailableResponse | HeroUnavailableResponse | HeroUnavailableAtHorizonResponse:
    return hero_service.get(delivery_date, run_id, horizon, legacy_day=day)
