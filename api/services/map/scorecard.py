"""Day-scoped scorecard selection for the Map workspace."""

from __future__ import annotations

from datetime import date

from psycopg.rows import dict_row

from api.db import get_pool
from api.schemas.map import MapScorecard, MapScorecardSource

_SERIES = ("model", "persistence", "oracle")
_DAILY_SOURCES = {
    "scoreboard_model_served_nodal": "model",
    "scoreboard_persistence_prior_day_nodal": "persistence",
    "scoreboard_oracle_settled_mu_nodal": "oracle",
}
_WEEKLY_SOURCES = {
    "scoreboard_model_backtest_nodal": "model",
    "scoreboard_persistence_backtest_nodal": "persistence",
    "scoreboard_oracle_backtest_nodal": "oracle",
}


def _sources(rows: list[dict], identities: dict[str, str]) -> list[MapScorecardSource]:
    by_series = {identities[row["source"]]: row for row in rows}
    return [
        MapScorecardSource(
            source_id=by_series[series]["source"],
            series_id=series,
            rank_spearman=by_series[series]["rank_spearman"],
            sign_agree=by_series[series]["sign_agree"],
            topdecile_hit=by_series[series]["topdecile_hit"],
        )
        for series in _SERIES
    ]


def _complete(rows: list[dict], identities: dict[str, str]) -> bool:
    return {identities.get(row["source"]) for row in rows} == set(_SERIES)


def build(delivery_date: date, run_id: str | None = None) -> MapScorecard:
    """Return the selected day's final, pending, or historical scorecard."""
    requested_run_id = run_id
    run_clause = " AND run_id = %s::text" if requested_run_id is not None else ""
    daily_params = (delivery_date, list(_DAILY_SOURCES), requested_run_id) if requested_run_id else (
        delivery_date,
        list(_DAILY_SOURCES),
    )
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"""
            SELECT run_id, source, rank_spearman, sign_agree, topdecile_hit
            FROM scoreboard_daily
            WHERE delivery_date = %s AND horizon = 1 AND source = ANY(%s)
              {run_clause}
            ORDER BY run_id, source
            """,
            daily_params,
        )
        daily_rows = cur.fetchall()
        daily_runs = {row["run_id"] for row in daily_rows}
        for daily_run_id in sorted(daily_runs):
            rows = [row for row in daily_rows if row["run_id"] == daily_run_id]
            if _complete(rows, _DAILY_SOURCES):
                return MapScorecard(
                    available=True,
                    basis="served_daily",
                    run_id=daily_run_id,
                    delivery_date=delivery_date,
                    horizon=1,
                    sources=_sources(rows, _DAILY_SOURCES),
                )

        pending_params = (delivery_date, delivery_date, requested_run_id) if requested_run_id else (
            delivery_date,
            delivery_date,
        )
        cur.execute(
            f"""
            SELECT run_id
            FROM (
                SELECT run_id FROM forecast_nodal
                WHERE delivery_date = %s AND horizon = 1
                UNION
                SELECT run_id FROM forecast_sf_artifact
                WHERE delivery_date = %s AND horizon = 1
            ) AS served
            WHERE TRUE {run_clause}
            ORDER BY run_id
            LIMIT 1
            """,
            pending_params,
        )
        pending_row = cur.fetchone()
        if pending_row is not None:
            return MapScorecard(
                available=True,
                basis="served_daily_pending",
                run_id=pending_row["run_id"],
                delivery_date=delivery_date,
                horizon=1,
            )

        cur.execute(
            """
            SELECT run_id, week, source, rank_spearman, sign_agree, topdecile_hit
            FROM scoreboard_weekly
            WHERE source = ANY(%s) AND week <= %s AND %s < week + 7
            ORDER BY week DESC, run_id, source
            """,
            (list(_WEEKLY_SOURCES), delivery_date, delivery_date),
        )
        weekly_rows = cur.fetchall()

    for weekly_run_id in sorted({row["run_id"] for row in weekly_rows}):
        rows = [row for row in weekly_rows if row["run_id"] == weekly_run_id]
        if _complete(rows, _WEEKLY_SOURCES):
            return MapScorecard(
                available=True,
                basis="weekly_backtest_fallback",
                run_id=weekly_run_id,
                delivery_date=delivery_date,
                scored_week=rows[0]["week"],
                sources=_sources(rows, _WEEKLY_SOURCES),
            )

    return MapScorecard(
        available=False,
        unavailable_reason="no_complete_scorecard",
        delivery_date=delivery_date,
    )
