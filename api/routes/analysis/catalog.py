"""Node and artifact catalog endpoints."""
from fastapi import APIRouter

from api.services.analysis import panels
from api.schemas.analysis import (
    AnalysisConstraintsAvailableResponse, AnalysisConstraintsUnavailableResponse,
    AnalysisEsspGroupsAvailableResponse, AnalysisEsspGroupsUnavailableResponse,
    AnalysisSettlementPointsAvailableResponse, AnalysisSettlementPointsUnavailableResponse,
    NodeAnalysisAvailableResponse, NodeAnalysisUnavailableResponse,
)

router = APIRouter(prefix="/analysis")
router.add_api_route("/node", panels.get_node, methods=["GET"],
                     response_model=NodeAnalysisAvailableResponse | NodeAnalysisUnavailableResponse,
                     summary="Full SF-column constraint attribution for a settlement point")
router.add_api_route("/settlement-points", panels.get_settlement_points, methods=["GET"],
                     response_model=AnalysisSettlementPointsAvailableResponse | AnalysisSettlementPointsUnavailableResponse,
                     summary="Full settlement-point vocabulary for a daily SF artifact")
router.add_api_route("/constraints", panels.get_constraints, methods=["GET"],
                     response_model=AnalysisConstraintsAvailableResponse | AnalysisConstraintsUnavailableResponse,
                     summary="Full constraint vocabulary for a daily SF artifact")
router.add_api_route("/essp", panels.get_essp_groups, methods=["GET"],
                     response_model=AnalysisEsspGroupsAvailableResponse | AnalysisEsspGroupsUnavailableResponse,
                     summary="Hourly ERCOT electrically-similar settlement-point groups")
