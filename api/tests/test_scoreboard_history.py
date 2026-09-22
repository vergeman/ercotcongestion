"""Tests for the summary's composed backtest and served-final chart history."""
from __future__ import annotations

from datetime import date

from api.services import scoreboard as scoreboard_service
from api.schemas.scoreboard import ScoreboardWeekly


def _weekly(week: date, source: str = "model", **extra):
    return {"week": week, "source_id": f"scoreboard_{source}_backtest_nodal", "series_id": source, **extra}


def _daily(day: date, source: str = "scoreboard_model_served_nodal", **extra):
    return {"delivery_date": day, "source": source, **extra}


def _board(*points):
    return ScoreboardWeekly(
        run_id="walk-v1",
        primary_source_id="scoreboard_model_backtest_nodal",
        rtc_b_cutover=date(2025, 12, 5),
        points=list(points),
        splits=[],
    )


def test_history_returns_weekly_fallback_and_final_served_points(fake_pool):
    fake_pool.cursor.queue([
        {"run_id": "served-v2"},
    ])
    fake_pool.cursor.queue([
        _daily(date(2026, 7, 18), rank_spearman=0.4),
        _daily(date(2026, 7, 19), rank_spearman=0.5),
    ])

    history = scoreboard_service.build_history(_board(
        _weekly(date(2026, 7, 4), rank_spearman=0.2),
        _weekly(date(2026, 7, 11), rank_spearman=0.3),
    ))

    assert history.weekly_run_id == "walk-v1"
    assert history.daily_run_id == "served-v2"
    assert all("source" not in point.model_dump() for point in history.weekly_points)
    assert all("source" not in point.model_dump() for point in history.served_daily_points)
    assert "primary_source" not in history.model_dump()
    assert "points" not in history.model_dump()
    assert [(p.week, p.delivery_date) for p in history.weekly_points] == [
        (date(2026, 7, 4), None),
        (date(2026, 7, 11), None),
    ]
    assert [(p.week, p.delivery_date) for p in history.served_daily_points] == [
        (None, date(2026, 7, 18)),
        (None, date(2026, 7, 19)),
    ]


def test_history_prefers_served_points_over_same_day_weekly_points(fake_pool):
    fake_pool.cursor.queue([{"run_id": "served-v2"}])
    fake_pool.cursor.queue([_daily(date(2026, 7, 11), rank_spearman=0.5)])

    history = scoreboard_service.build_history(_board(
        _weekly(date(2026, 7, 4), rank_spearman=0.2),
        _weekly(date(2026, 7, 11), rank_spearman=0.3),
        _weekly(date(2026, 7, 11), source="persistence", rank_spearman=0.4),
    ))

    assert [(point.week, point.series_id) for point in history.weekly_points] == [
        (date(2026, 7, 4), "model"),
        (date(2026, 7, 11), "persistence"),
    ]
    assert [point.delivery_date for point in history.served_daily_points] == [
        date(2026, 7, 11)
    ]


def test_history_selects_h1_only(fake_pool):
    fake_pool.cursor.queue([{"run_id": "served-v1"}])
    fake_pool.cursor.queue([_daily(date(2026, 7, 18))])

    scoreboard_service.build_history(_board(_weekly(date(2026, 7, 11))))

    assert "WHERE horizon = 1" in fake_pool.cursor.queries[0][0]
    assert "horizon = 1" in fake_pool.cursor.queries[1][0]


def test_history_keeps_backtest_when_no_final_grade_exists(fake_pool):
    fake_pool.cursor.queue([])

    history = scoreboard_service.build_history(_board(_weekly(date(2026, 7, 11))))

    assert history.daily_run_id is None
    assert history.served_daily_points == []
    assert [p.week for p in history.weekly_points] == [date(2026, 7, 11)]


def test_history_preserves_independent_weekly_and_daily_run_provenance(fake_pool):
    fake_pool.cursor.queue([{"run_id": "served-v3"}])
    fake_pool.cursor.queue([_daily(date(2026, 7, 18))])

    history = scoreboard_service.build_history(_board(_weekly(date(2026, 7, 11))))

    assert history.weekly_run_id == "walk-v1"
    assert history.daily_run_id == "served-v3"


def test_summary_exposes_scoreboard_history_schemas(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert {"ScoreboardHistory", "ScoreHistoryPoint"} <= set(schemas)
    assert "/scoreboard/history" not in client.get("/openapi.json").json()["paths"]
