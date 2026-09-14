"""Analysis hero endpoints."""

from fastapi import APIRouter, Depends

from api.dependencies import server_selected_run as _server_selected_run
from api.services.analysis.features import hero as hero_service
from api.schemas.analysis import (
    HeroLatestResponse,
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
