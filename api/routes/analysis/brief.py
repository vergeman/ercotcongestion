"""Brief HTTP endpoints."""
from datetime import date

from fastapi import APIRouter, Depends, Query

from dependencies import server_selected_run as _server_selected_run
from schemas.analysis import BriefDayResponse, BriefDetailsResponse, BriefHeroShellResponse, BriefHeroStatsResponse
from services.analysis import brief as brief_service

router = APIRouter(prefix="/analysis")


@router.get("/brief/hero", response_model=BriefHeroShellResponse,
            summary="Brief hero and available neighbouring delivery dates")
def get_brief_hero_shell(
    delivery_date: date | None = Query(None, description="ERCOT delivery day."),
    run_id: str | None = Depends(_server_selected_run),
    *,
    day: date | None = Query(None, deprecated=True, description="Deprecated alias for delivery_date."),
) -> BriefHeroShellResponse:
    return brief_service.hero_shell(delivery_date, run_id, day)


@router.get("/brief/hero/stats", response_model=BriefHeroStatsResponse,
            summary="Complete grouped stat-card evidence for a Brief hero")
def get_brief_hero_stats(
    delivery_date: date | None = Query(None, description="ERCOT delivery day."),
    run_id: str | None = Depends(_server_selected_run),
    *,
    day: date | None = Query(None, deprecated=True, description="Deprecated alias for delivery_date."),
) -> BriefHeroStatsResponse:
    return brief_service.hero_stats(delivery_date, run_id, day)


@router.get("/brief/details", response_model=BriefDetailsResponse,
            summary="Secondary Brief sections for one delivery day")
def get_brief_details(
    delivery_date: date | None = Query(None, description="ERCOT delivery day."),
    run_id: str | None = Depends(_server_selected_run),
    include_standouts: bool = Query(True, description="Include the standouts panel in this bundle."),
    *,
    day: date | None = Query(None, deprecated=True, description="Deprecated alias for delivery_date."),
) -> BriefDetailsResponse:
    return brief_service.details(delivery_date, run_id, include_standouts, day)


@router.get("/brief", response_model=BriefDayResponse,
            summary="One bundled payload for a Brief delivery day (0137)")
def get_brief_day(
    delivery_date: date | None = Query(None, description="ERCOT delivery day."),
    run_id: str | None = Depends(_server_selected_run),
    *,
    day: date | None = Query(None, deprecated=True, description="Deprecated alias for delivery_date."),
) -> BriefDayResponse:
    return brief_service.day(delivery_date, run_id, day)
