"""Node and artifact catalog endpoints."""
from fastapi import APIRouter

import analysis
from schemas.analysis import (
    AnalysisConstraintsAvailableResponse, AnalysisConstraintsUnavailableResponse,
    AnalysisEsspGroupsAvailableResponse, AnalysisEsspGroupsUnavailableResponse,
    AnalysisSettlementPointsAvailableResponse, AnalysisSettlementPointsUnavailableResponse,
    ForecastMuAvailableResponse, ForecastMuUnavailableResponse,
    NodeAnalysisAvailableResponse, NodeAnalysisUnavailableResponse,
)

router = APIRouter(prefix="/analysis")
router.add_api_route("/node", analysis.get_node, methods=["GET"],
                     response_model=NodeAnalysisAvailableResponse | NodeAnalysisUnavailableResponse,
                     summary="Full SF-column constraint attribution for a settlement point")
router.add_api_route("/settlement-points", analysis.get_settlement_points, methods=["GET"],
                     response_model=AnalysisSettlementPointsAvailableResponse | AnalysisSettlementPointsUnavailableResponse,
                     summary="Full settlement-point vocabulary for a daily SF artifact")
router.add_api_route("/constraints", analysis.get_constraints, methods=["GET"],
                     response_model=AnalysisConstraintsAvailableResponse | AnalysisConstraintsUnavailableResponse,
                     summary="Full constraint vocabulary for a daily SF artifact")
router.add_api_route("/essp", analysis.get_essp_groups, methods=["GET"],
                     response_model=AnalysisEsspGroupsAvailableResponse | AnalysisEsspGroupsUnavailableResponse,
                     summary="Hourly ERCOT electrically-similar settlement-point groups")
router.add_api_route("/forecast-mu", analysis.get_forecast_mu, methods=["GET"],
                     response_model=ForecastMuAvailableResponse | ForecastMuUnavailableResponse,
                     summary="Hourly forecast μ for selected artifact constraints")
