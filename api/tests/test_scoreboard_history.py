"""Tests for the composed weekly-backtest and served-final chart history."""
from __future__ import annotations

from datetime import date


def _weekly(week: date, source: str = "model", **extra):
    return {"week": week, "source": source, **extra}


def _daily(day: date, source: str = "model", **extra):
    return {"delivery_date": day, "source": source, **extra}


def test_history_orders_weekly_points_before_final_served_points(client, fake_pool):
    fake_pool.cursor.queue([
        _weekly(date(2026, 7, 4), rank_spearman=0.2),
        _weekly(date(2026, 7, 11), rank_spearman=0.3),
    ])
    fake_pool.cursor.queue([{"run_id": "served-v2"}])
    fake_pool.cursor.queue([
        _daily(date(2026, 7, 18), rank_spearman=0.4),
        _daily(date(2026, 7, 19), rank_spearman=0.5),
    ])

    response = client.get("/scoreboard/history", params={"run_id": "walk-v1"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["weekly_run_id"] == "walk-v1"
    assert body["daily_run_id"] == "served-v2"
    assert body["boundary_date"] == "2026-07-18"
    assert [(p["cadence"], p["week"], p["delivery_date"]) for p in body["points"]] == [
        ("backtest_weekly", "2026-07-04", None),
        ("backtest_weekly", "2026-07-11", None),
        ("served_daily", None, "2026-07-18"),
        ("served_daily", None, "2026-07-19"),
    ]


def test_history_selects_h1_only(client, fake_pool):
    fake_pool.cursor.queue([_weekly(date(2026, 7, 11))])
    fake_pool.cursor.queue([{"run_id": "served-v1"}])
    fake_pool.cursor.queue([_daily(date(2026, 7, 18))])

    response = client.get("/scoreboard/history", params={"run_id": "walk-v1"})

    assert response.status_code == 200, response.text
    assert "WHERE horizon = 1" in fake_pool.cursor.queries[1][0]
    assert "horizon = 1" in fake_pool.cursor.queries[2][0]


def test_history_keeps_backtest_when_no_final_grade_exists(client, fake_pool):
    fake_pool.cursor.queue([_weekly(date(2026, 7, 11))])
    fake_pool.cursor.queue([])

    response = client.get("/scoreboard/history", params={"run_id": "walk-v1"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["daily_run_id"] is None
    assert body["boundary_date"] is None
    assert [p["cadence"] for p in body["points"]] == ["backtest_weekly"]


def test_history_resolves_weekly_and_daily_runs_independently(client, fake_pool):
    fake_pool.cursor.queue([{"run_id": "walk-v1"}])
    fake_pool.cursor.queue([_weekly(date(2026, 7, 11))])
    fake_pool.cursor.queue([{"run_id": "served-v3"}])
    fake_pool.cursor.queue([_daily(date(2026, 7, 18))])

    response = client.get("/scoreboard/history")

    assert response.status_code == 200, response.text
    assert response.json()["weekly_run_id"] == "walk-v1"
    assert response.json()["daily_run_id"] == "served-v3"


def test_openapi_exposes_scoreboard_history_schemas(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    assert {"ScoreboardHistory", "ScoreHistoryPoint"} <= set(schemas)
