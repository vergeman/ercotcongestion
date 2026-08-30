"""Tests for GET /scoreboard/summary — the bundled load-time trio (0137).

Mirrors test_analysis.py's brief-day composition test: monkeypatch the three
section handlers directly rather than threading fake rows through their own
(already separately tested) query logic. `ScoreboardSummaryResponse(...)` is
constructed — and so validated by Pydantic — inside `get_scoreboard_summary`
itself, so the fakes below must return real (if minimal) instances of each
section's response model, not bare stand-ins.
"""
from __future__ import annotations

from datetime import date

from fastapi import HTTPException

import scoreboard as scoreboard_module
from models import ScoreboardDaily, ScoreboardHeadline, ScoreboardHistory, ScoreboardWeekly

WEEKLY = ScoreboardWeekly(run_id="r", primary_source="model",
                          rtc_b_cutover=date(2025, 12, 5), points=[], splits=[])
HEADLINE = ScoreboardHeadline(run_id="r", as_of_week=date(2026, 7, 1), windows=[])
DAILY = ScoreboardDaily(run_id="r", primary_source="model", horizon=1,
                        selected_delivery_date=date(2026, 7, 18), points=[])
HISTORY = ScoreboardHistory(primary_source="model", weekly_run_id="r", points=[])


def test_summary_calls_each_internal_section(monkeypatch):
    calls: dict[str, tuple] = {}

    def _fake(name, result):
        def _handler(*args):
            calls[name] = args
            return result
        return _handler

    monkeypatch.setattr(scoreboard_module, "build_scoreboard_weekly", _fake("weekly", WEEKLY))
    monkeypatch.setattr(scoreboard_module, "build_headline", _fake("headline", HEADLINE))
    monkeypatch.setattr(scoreboard_module, "build_latest_final_daily", _fake("daily", DAILY))
    monkeypatch.setattr(scoreboard_module, "build_scoreboard_history", _fake("history", HISTORY))

    body = scoreboard_module.get_scoreboard_summary()

    assert calls == {
        "weekly": (),
        "headline": (None,),
        "daily": (),
        "history": (WEEKLY,),
    }
    assert body.weekly == WEEKLY
    assert body.headline == HEADLINE
    assert body.daily == DAILY
    assert body.history == HISTORY
    assert body.availability['daily'].available is True
    assert body.availability['daily'].run_id == 'r'


def test_summary_turns_a_sections_503_into_a_null_field_without_failing_the_rest(
    monkeypatch,
):
    """A board with no rows yet (e.g. no live grade before any DAM lands) must
    not take down the sections that do have data — same soft-fail the client
    already applies per single-section endpoint (503 -> null)."""
    def _unavailable(*args):
        raise HTTPException(status_code=503, detail="no board loaded")

    monkeypatch.setattr(scoreboard_module, "build_scoreboard_weekly", lambda *a: WEEKLY)
    monkeypatch.setattr(scoreboard_module, "build_headline", lambda *a: HEADLINE)
    monkeypatch.setattr(scoreboard_module, "build_latest_final_daily", _unavailable)
    monkeypatch.setattr(scoreboard_module, "build_scoreboard_history", lambda *a: HISTORY)

    body = scoreboard_module.get_scoreboard_summary()

    assert body.weekly == WEEKLY
    assert body.headline == HEADLINE
    assert body.daily is None
    assert body.history == HISTORY
    assert body.availability['daily'].available is False
    assert body.availability['daily'].unavailable_reason == 'source_unavailable'


def test_summary_reraises_a_non_503_error(monkeypatch):
    """Only the documented soft-fail (503, no board loaded) is swallowed —
    any other error must still surface, not be silently hidden as null."""
    def _broken(*args):
        raise HTTPException(status_code=500, detail="boom")

    monkeypatch.setattr(scoreboard_module, "build_scoreboard_weekly", _broken)
    monkeypatch.setattr(scoreboard_module, "build_headline", lambda *a: HEADLINE)
    monkeypatch.setattr(scoreboard_module, "build_latest_final_daily", lambda *a: DAILY)
    monkeypatch.setattr(scoreboard_module, "build_scoreboard_history", lambda *a: HISTORY)

    try:
        scoreboard_module.get_scoreboard_summary()
        assert False, "expected HTTPException to propagate"
    except HTTPException as exc:
        assert exc.status_code == 500
