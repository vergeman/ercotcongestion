"""Analysis ranking and context endpoints."""

from fastapi import APIRouter

from api.services.analysis import panels
from api.schemas.analysis import (
    StandoutsAvailableResponse,
    NodeAnalysisUnavailableResponse,
)

router = APIRouter(prefix="/analysis")
router.add_api_route(
    "/standouts",
    panels.get_standouts,
    methods=["GET"],
    response_model=StandoutsAvailableResponse | NodeAnalysisUnavailableResponse,
    summary="Forecast standouts against each constraint's own trailing forecast history",
)
