"""Analysis ranking and context endpoints."""

from fastapi import APIRouter

from api.services.analysis import brief
from api.schemas.analysis import (
    StandoutsAvailableResponse,
    NodeAnalysisUnavailableResponse,
)

router = APIRouter(prefix="/analysis")
router.add_api_route(
    "/standouts",
    brief.standouts,
    methods=["GET"],
    response_model=StandoutsAvailableResponse | NodeAnalysisUnavailableResponse,
    summary="Forecast standouts against each constraint's own trailing forecast history",
)
