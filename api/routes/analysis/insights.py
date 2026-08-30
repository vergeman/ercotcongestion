"""Analysis ranking and context endpoints."""
from fastapi import APIRouter

from api.services.analysis import panels
from api.schemas.analysis import (
    ContextAvailableResponse, ContextUnavailableResponse, StandoutsAvailableResponse,
    StandoutsUnavailableResponse, TopConstraintsAvailableResponse, TopConstraintsUnavailableResponse,
    TopNodesAvailableResponse, TopNodesUnavailableResponse,
)

router = APIRouter(prefix="/analysis")
router.add_api_route("/top-constraints", panels.get_top_constraints, methods=["GET"],
                     response_model=TopConstraintsAvailableResponse | TopConstraintsUnavailableResponse,
                     summary="Untruncated daily forecast-μ ranking with same-key DAM evidence")
router.add_api_route("/context", panels.get_context, methods=["GET"],
                     response_model=ContextAvailableResponse | ContextUnavailableResponse,
                     summary="Daily voltage-class distribution and trailing chronic constraints")
router.add_api_route("/standouts", panels.get_standouts, methods=["GET"],
                     response_model=StandoutsAvailableResponse | StandoutsUnavailableResponse,
                     summary="Forecast standouts against each constraint's own trailing forecast history")
router.add_api_route("/top-nodes", panels.get_top_nodes, methods=["GET"],
                     response_model=TopNodesAvailableResponse | TopNodesUnavailableResponse,
                     summary="Daily settlement-point ranking with same-point DAM evidence")
