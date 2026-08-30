"""Tests for the latest final-grade section of ``/scoreboard/summary``."""
from __future__ import annotations

from datetime import date

from fastapi import HTTPException

from services import scoreboard as scoreboard_service


def _row(source: str, **kw):
    base = {"delivery_date": date(2026, 7, 18), "source": source, "horizon": 1}
    base.update(kw)
    return base


def test_latest_final_selects_newest_final_grade_in_sql(fake_pool):
    newest = date(2026, 7, 19)
    fake_pool.cursor.queue([{"run_id": "mu-all-v2"}])
    fake_pool.cursor.queue([
        _row("model", delivery_date=newest, topdecile_hit=0.6),
        _row("persistence", delivery_date=newest, topdecile_hit=0.5),
        _row("oracle", delivery_date=newest, topdecile_hit=0.8),
    ])

    daily = scoreboard_service.build_latest_final_daily()

    assert daily.run_id == "mu-all-v2"
    assert daily.horizon == 1
    assert daily.selected_delivery_date == newest
    assert {point.delivery_date for point in daily.points} == {newest}
    sql, params = fake_pool.cursor.queries[-1]
    assert "SELECT max(delivery_date)" in sql
    assert "horizon = 1" in sql
    assert params == ("mu-all-v2", "mu-all-v2")


def test_latest_final_does_not_fall_back_to_preview(fake_pool):
    fake_pool.cursor.queue([])

    try:
        scoreboard_service.build_latest_final_daily()
        assert False, "expected unavailable final grade"
    except HTTPException as exc:
        assert exc.status_code == 503
        assert "no final live grades" in exc.detail
