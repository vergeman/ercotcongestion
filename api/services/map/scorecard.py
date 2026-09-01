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
    """Prefer this day's complete h1 grade; otherwise use one weekly set."""
    run_clause = " AND run_id = %s::text" if run_id is not None else ""
    daily_params = (delivery_date, list(_DAILY_SOURCES), run_id) if run_id else (
        delivery_date,
        list(_DAILY_SOURCES),
    )
    weekly_params = (list(_WEEKLY_SOURCES),)
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
        for run_id in sorted(daily_runs):
            rows = [row for row in daily_rows if row["run_id"] == run_id]
            if _complete(rows, _DAILY_SOURCES):
                return MapScorecard(
                    available=True,
                    basis="served_daily",
                    run_id=run_id,
                    delivery_date=delivery_date,
                    horizon=1,
                    sources=_sources(rows, _DAILY_SOURCES),
                )

        cur.execute(
            f"""
            SELECT run_id, week, source, rank_spearman, sign_agree, topdecile_hit
            FROM scoreboard_weekly
            WHERE source = ANY(%s)
            ORDER BY week DESC, run_id, source
            """,
            weekly_params,
        )
        weekly_rows = cur.fetchall()

    for week in sorted({row["week"] for row in weekly_rows}, reverse=True):
        week_rows = [row for row in weekly_rows if row["week"] == week]
        for run_id in sorted({row["run_id"] for row in week_rows}):
            rows = [row for row in week_rows if row["run_id"] == run_id]
            if _complete(rows, _WEEKLY_SOURCES):
                return MapScorecard(
                    available=True,
                    basis="weekly_backtest_fallback",
                    run_id=run_id,
                    delivery_date=delivery_date,
                    scored_week=week,
                    sources=_sources(rows, _WEEKLY_SOURCES),
                )

    return MapScorecard(
        available=False,
        unavailable_reason="no_complete_scorecard",
        delivery_date=delivery_date,
    )
