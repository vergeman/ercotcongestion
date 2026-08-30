"""Analysis grading endpoints."""
from fastapi import APIRouter

from api.services.analysis import panels
from api.schemas.analysis import (
    GradeAvailableResponse, GradeHistoryAvailableResponse, GradeHistoryUnavailableResponse,
    GradeUnavailableResponse,
)

router = APIRouter(prefix="/analysis")
router.add_api_route("/grade", panels.get_grade, methods=["GET"],
                     response_model=GradeAvailableResponse | GradeUnavailableResponse,
                     summary="Prototype-defined per-day forecast grade")
router.add_api_route("/grade-history", panels.get_grade_history, methods=["GET"],
                     response_model=GradeHistoryAvailableResponse | GradeHistoryUnavailableResponse,
                     summary="Materialized trailing v6 constraint and node grade")
