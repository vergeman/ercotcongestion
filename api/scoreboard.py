"""Scoreboard summary route."""
from fastapi import APIRouter

from schemas.scoreboard import ScoreboardSummaryResponse
from services.scoreboard import build_summary

router = APIRouter()


@router.get(
    "/scoreboard/summary",
    response_model=ScoreboardSummaryResponse,
    summary="One bundled payload for the Scoreboard page summary (0137)",
)
def get_scoreboard_summary() -> ScoreboardSummaryResponse:
    return build_summary()
