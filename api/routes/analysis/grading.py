"""Analysis grading endpoints."""
from fastapi import APIRouter

from api.services.analysis import panels
from api.schemas.analysis import GradeAvailableResponse, GradeUnavailableResponse

router = APIRouter(prefix="/analysis")
router.add_api_route("/grade", panels.get_grade, methods=["GET"],
                     response_model=GradeAvailableResponse | GradeUnavailableResponse,
                     summary="Prototype-defined per-day forecast grade")
