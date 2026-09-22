"""Tests for GET /scoreboard/summary sections.

Section builders are patched directly, so these tests cover composition rather
than individual queries.
"""
from __future__ import annotations

from datetime import date

from fastapi import HTTPException

from api.services import scoreboard as scoreboard_service
from api.schemas.scoreboard import ScoreboardDaily, ScoreboardHistory, ScoreboardWeekly

WEEKLY = ScoreboardWeekly(run_id="r", primary_source_id="scoreboard_model_backtest_nodal",
                          rtc_b_cutover=date(2025, 12, 5), points=[], splits=[])
DAILY = ScoreboardDaily(run_id="r", primary_source_id="scoreboard_model_served_nodal", horizon=1,
                        selected_delivery_date=date(2026, 7, 18), points=[])
HISTORY = ScoreboardHistory(
    primary_source_id="scoreboard_model_backtest_nodal", weekly_run_id="r", weekly_points=[]
)


def test_summary_calls_each_internal_section(monkeypatch):
    calls: dict[str, tuple] = {}

    def _fake(name, result):
        def _handler(*args):
            calls[name] = args
            return result
        return _handler

    monkeypatch.setattr(scoreboard_service, "build_weekly", _fake("weekly", WEEKLY))
    monkeypatch.setattr(scoreboard_service, "build_latest_final_daily", _fake("daily", DAILY))
    monkeypatch.setattr(scoreboard_service, "build_history", _fake("history", HISTORY))

    body = scoreboard_service.build_summary()

    assert calls == {
        "weekly": (),
        "daily": (),
        "history": (WEEKLY,),
    }
    assert body.weekly == WEEKLY
    assert body.daily == DAILY
    assert body.history == HISTORY
    assert body.availability['daily'].available is True
    assert body.availability['daily'].run_id == 'r'
    assert "headline" not in body.model_dump()
    assert "headline" not in body.availability


def test_summary_turns_a_sections_503_into_a_null_field_without_failing_the_rest(
    monkeypatch,
):
    """A board with no rows yet (e.g. no live grade before any DAM lands) must
    not take down the sections that do have data — same soft-fail the client
    already applies per single-section endpoint (503 -> null)."""
    def _unavailable(*args):
        raise HTTPException(status_code=503, detail="no board loaded")

    monkeypatch.setattr(scoreboard_service, "build_weekly", lambda *a: WEEKLY)
    monkeypatch.setattr(scoreboard_service, "build_latest_final_daily", _unavailable)
    monkeypatch.setattr(scoreboard_service, "build_history", lambda *a: HISTORY)

    body = scoreboard_service.build_summary()

    assert body.weekly == WEEKLY
    assert body.daily is None
    assert body.history == HISTORY
    assert body.availability['daily'].available is False
    assert body.availability['daily'].unavailable_reason == 'source_unavailable'


def test_summary_reraises_a_non_503_error(monkeypatch):
    """Only the documented soft-fail (503, no board loaded) is swallowed —
    any other error must still surface, not be silently hidden as null."""
    def _broken(*args):
        raise HTTPException(status_code=500, detail="boom")

    monkeypatch.setattr(scoreboard_service, "build_weekly", _broken)
    monkeypatch.setattr(scoreboard_service, "build_latest_final_daily", lambda *a: DAILY)
    monkeypatch.setattr(scoreboard_service, "build_history", lambda *a: HISTORY)

    try:
        scoreboard_service.build_summary()
        assert False, "expected HTTPException to propagate"
    except HTTPException as exc:
        assert exc.status_code == 500
