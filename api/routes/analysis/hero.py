"""Analysis hero endpoints."""

from fastapi import APIRouter

from api.services.analysis import panels
from api.schemas.analysis import (
    HeroAvailableResponse,
    HeroLatestResponse,
    HeroUnavailableAtHorizonResponse,
    HeroUnavailableResponse,
)

router = APIRouter(prefix="/analysis")
router.add_api_route(
    "/hero/latest",
    panels.get_hero_latest,
    methods=["GET"],
    response_model=HeroLatestResponse,
    summary="Newest v6 Brief delivery day with a published artifact",
)
router.add_api_route(
    "/hero",
    panels.get_hero,
    methods=["GET"],
    response_model=HeroAvailableResponse
    | HeroUnavailableResponse
    | HeroUnavailableAtHorizonResponse,
    summary="Server-computed v6 daily-brief hero",
)
