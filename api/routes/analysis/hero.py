"""Analysis hero endpoints."""
from fastapi import APIRouter

import analysis
from schemas.analysis import HeroAvailableResponse, HeroLatestResponse, HeroUnavailableAtHorizonResponse, HeroUnavailableResponse

router = APIRouter(prefix="/analysis")
router.add_api_route("/hero/latest", analysis.get_hero_latest, methods=["GET"],
                     response_model=HeroLatestResponse,
                     summary="Newest v6 Brief delivery day with a published artifact")
router.add_api_route("/hero", analysis.get_hero, methods=["GET"],
                     response_model=HeroAvailableResponse | HeroUnavailableResponse | HeroUnavailableAtHorizonResponse,
                     summary="Server-computed v6 daily-brief hero")
