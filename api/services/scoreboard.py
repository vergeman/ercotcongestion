"""Scoreboard summary data builders."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date

from fastapi import HTTPException
from psycopg.rows import dict_row

from api.db import get_pool
from api.schemas.common import BootstrapSectionStatus, SourceDescriptor
from api.schemas.scoreboard import (
    DailyPoint,
    ScoreboardDaily,
    ScoreboardHistory,
    ScoreboardSummaryResponse,
    ScoreboardWeekly,
    ScoreHistoryPoint,
    SourcePooled,
    WeeklyPoint,
    WeeklySplit,
)
from api.services.bootstrap import availability_status, soft_fail
from api.services.scoreboard_headline import build_headline

@dataclass(frozen=True)
class SourceDefinition:
    """Scoreboard API-owned provenance and logical chart series."""

    id: str
    series_id: str
    label: str
    definition: str


WEEKLY_SOURCE_DEFINITIONS = (
    SourceDefinition("scoreboard_model_backtest_nodal", "model", "Model Forecast",
                         "Walk-forward model projected to nodal congestion."),
    SourceDefinition("scoreboard_persistence_backtest_nodal", "persistence", "Prior-day (Persistence)",
                         "Prior-day μ baseline projected by each backtest map."),
    SourceDefinition("scoreboard_climatology_backtest_nodal", "climatology", "Trailing-window average (Baseline)",
                         "Hourly μ climatology projected by each backtest map."),
    SourceDefinition("scoreboard_oracle_backtest_nodal", "oracle", "Settled-μ ceiling (Oracle)",
                         "Realized μ projected by the held-out backtest map."),
    SourceDefinition("scoreboard_null_flat_nodal", "null", "Flat nodal control",
                         "Flat nodal congestion tripwire."),
)
DAILY_SOURCE_DEFINITIONS = (
    SourceDefinition("scoreboard_model_served_nodal", "model", "Model Forecast",
                         "Served deterministic nodal forecast."),
    SourceDefinition("scoreboard_persistence_prior_day_nodal", "persistence", "Prior-day (Persistence)",
                         "Prior-day μ projected through the trailing map."),
    SourceDefinition("scoreboard_climatology_trailing_window_nodal", "climatology", "Trailing-window average (Baseline)",
                         "Trailing-window μ climatology projected through the map."),
    SourceDefinition("scoreboard_oracle_settled_mu_nodal", "oracle", "Settled-μ ceiling (Oracle)",
                         "Settled-day μ projected through the trailing map."),
    SourceDefinition("scoreboard_null_flat_nodal", "null", "Flat nodal control",
                         "Flat nodal congestion tripwire."),
)
_WEEKLY_BY_ID = {source.id: source for source in WEEKLY_SOURCE_DEFINITIONS}
_DAILY_BY_ID = {source.id: source for source in DAILY_SOURCE_DEFINITIONS}
_SOURCES = tuple(source.id for source in WEEKLY_SOURCE_DEFINITIONS if source.series_id != "null")
_POOL_METRICS = ("rank_spearman", "sign_agree", "topdecile_hit")
RTC_B_CUTOVER = date(2025, 12, 5)


def _resolve_weekly_run_id(cur) -> str:
    cur.execute(
        "SELECT run_id FROM scoreboard_weekly ORDER BY week DESC, run_id LIMIT 1"
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(
            status_code=503,
            detail="no scoreboard board is loaded (scoreboard_weekly is empty).",
        )
    return row["run_id"]


def _mean(rows: list[dict], key: str) -> float | None:
    vals = [row[key] for row in rows if row[key] is not None]
    return sum(vals) / len(vals) if vals else None


def _pooled_source(rows: list[dict], source: str) -> SourcePooled:
    source_rows = [row for row in rows if row["source"] == source]
    return SourcePooled(
        source_id=source,
        series_id=_WEEKLY_BY_ID[source].series_id,
        **{key: _mean(source_rows, key) for key in _POOL_METRICS},
    )


def _beats_persistence(model: SourcePooled, persistence: SourcePooled) -> bool:
    """Require the model to beat persistence on every scoreboard gate metric."""
    return all(
        getattr(model, key) > getattr(persistence, key)
        for key in _POOL_METRICS
    )


def _build_splits(rows: list[dict]) -> list[WeeklySplit]:
    slices = [
        ("all", rows),
        ("pre_rtc_b", [row for row in rows if row["week"] < RTC_B_CUTOVER]),
        ("post_rtc_b", [row for row in rows if row["week"] >= RTC_B_CUTOVER]),
    ]
    splits: list[WeeklySplit] = []
    for label, slice_rows in slices:
        pooled = {source: _pooled_source(slice_rows, source) for source in _SOURCES}
        model = pooled["scoreboard_model_backtest_nodal"]
        persistence = pooled["scoreboard_persistence_backtest_nodal"]
        beats: bool | None = None
        if all(getattr(model, key) is not None for key in _POOL_METRICS) and all(
            getattr(persistence, key) is not None for key in _POOL_METRICS
        ):
            beats = _beats_persistence(model, persistence)
        splits.append(
            WeeklySplit(
                label=label,
                n_weeks=len({row["week"] for row in slice_rows}),
                sources=[pooled[source] for source in _SOURCES],
                beats_persistence=beats,
            )
        )
    return splits


def build_weekly() -> ScoreboardWeekly:
    """Build the weekly summary section."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id = _resolve_weekly_run_id(cur)
        cur.execute(
            """
            SELECT week, source, rank_spearman, sign_agree, topdecile_hit,
                   sf_coverage, model_coverage, n_hours, n_nodes
            FROM scoreboard_weekly
            WHERE run_id = %s
            ORDER BY week, source
            """,
            (run_id,),
        )
        rows = cur.fetchall()

    if not rows:
        raise HTTPException(
            status_code=503,
            detail=(
                f"no scoreboard_weekly rows for run_id={run_id}. "
                "Load the board first (compute.jobs.backfill_scoreboard)."
            ),
        )
    return ScoreboardWeekly(
        run_id=run_id,
        primary_source_id="scoreboard_model_backtest_nodal",
        rtc_b_cutover=RTC_B_CUTOVER,
        points=[WeeklyPoint(**{**row, "source_id": row["source"],
                              "series_id": _WEEKLY_BY_ID[row["source"]].series_id})
                for row in rows],
        splits=_build_splits(rows),
        sources=[SourceDescriptor(**source.__dict__)
                 for source in WEEKLY_SOURCE_DEFINITIONS],
    )


def _resolve_latest_final_daily_run_id(cur) -> str:
    cur.execute(
        "SELECT run_id FROM scoreboard_daily WHERE horizon = 1 "
        "ORDER BY delivery_date DESC, run_id LIMIT 1"
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(
            status_code=503,
            detail="no final live grades yet (scoreboard_daily has no horizon=1 rows).",
        )
    return row["run_id"]


def build_latest_final_daily() -> ScoreboardDaily:
    """Build the newest fully persisted final grade and comparator rows."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id = _resolve_latest_final_daily_run_id(cur)
        cur.execute(
            """
            SELECT delivery_date, source, horizon, rank_spearman, sign_agree,
                   topdecile_hit, sf_coverage, model_coverage, n_hours, n_nodes
            FROM scoreboard_daily
            WHERE run_id = %s AND horizon = 1
              AND delivery_date = (
                  SELECT max(delivery_date)
                  FROM scoreboard_daily
                  WHERE run_id = %s AND horizon = 1
              )
            ORDER BY delivery_date, source
            """,
            (run_id, run_id),
        )
        rows = cur.fetchall()

    if not rows:
        raise HTTPException(
            status_code=503,
            detail=(
                f"no final scoreboard_daily rows for run_id={run_id}. "
                "Grade a served day first (compute.jobs.grade_forecast_day)."
            ),
        )
    return ScoreboardDaily(
        run_id=run_id,
        primary_source_id="scoreboard_model_served_nodal",
        horizon=1,
        selected_delivery_date=rows[0]["delivery_date"],
        points=[DailyPoint(**{**row, "source_id": row["source"],
                             "series_id": _DAILY_BY_ID[row["source"]].series_id})
                for row in rows],
        sources=[SourceDescriptor(**source.__dict__)
                 for source in DAILY_SOURCE_DEFINITIONS],
    )


def build_history(weekly: ScoreboardWeekly) -> ScoreboardHistory:
    """Append final served grades to an already-resolved weekly board."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT run_id FROM scoreboard_daily
            WHERE horizon = 1
            ORDER BY delivery_date DESC, run_id
            LIMIT 1
            """
        )
        live_run = cur.fetchone()
        daily_run_id = live_run["run_id"] if live_run else None
        daily_rows: list[dict] = []
        if daily_run_id is not None:
            cur.execute(
                """
                SELECT delivery_date, source, rank_spearman, sign_agree,
                       topdecile_hit, sf_coverage, model_coverage, n_hours, n_nodes
                FROM scoreboard_daily
                WHERE run_id = %s AND horizon = 1
                ORDER BY delivery_date, source
                """,
                (daily_run_id,),
            )
            daily_rows = cur.fetchall()

    points = [
        ScoreHistoryPoint(cadence="backtest_weekly", **point.model_dump())
        for point in weekly.points
    ]
    points.extend(
        ScoreHistoryPoint(cadence="served_daily", **{
            **row, "source_id": row["source"],
            "series_id": _DAILY_BY_ID[row["source"]].series_id,
        }) for row in daily_rows
    )
    return ScoreboardHistory(
        primary_source_id=weekly.primary_source_id,
        weekly_run_id=weekly.run_id,
        daily_run_id=daily_run_id,
        boundary_date=min((row["delivery_date"] for row in daily_rows), default=None),
        points=points,
        sources=[SourceDescriptor(**source.__dict__)
                 for source in WEEKLY_SOURCE_DEFINITIONS + DAILY_SOURCE_DEFINITIONS
                 if source.id != "scoreboard_null_flat_nodal"
                 or source in WEEKLY_SOURCE_DEFINITIONS],
    )


def build_summary() -> ScoreboardSummaryResponse:
    """Compose independently available Scoreboard sections."""
    with ThreadPoolExecutor(max_workers=3) as pool:
        weekly = pool.submit(soft_fail, build_weekly)
        headline = pool.submit(soft_fail, lambda: build_headline(None))
        daily = pool.submit(soft_fail, build_latest_final_daily)
        weekly_result = weekly.result()
        headline_result = headline.result()
        daily_result = daily.result()
        history_result = (
            soft_fail(lambda: build_history(weekly_result))
            if weekly_result is not None
            else None
        )
    return ScoreboardSummaryResponse(
        weekly=weekly_result,
        headline=headline_result,
        daily=daily_result,
        history=history_result,
        availability={
            "weekly": availability_status(weekly_result, BootstrapSectionStatus),
            "headline": availability_status(headline_result, BootstrapSectionStatus),
            "daily": availability_status(daily_result, BootstrapSectionStatus),
            "history": availability_status(history_result, BootstrapSectionStatus),
        },
    )
