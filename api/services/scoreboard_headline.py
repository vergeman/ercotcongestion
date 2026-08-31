"""Headline assembly shared by the Scoreboard route and Map bootstrap."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import HTTPException
from psycopg.rows import dict_row

from api.db import get_pool
from api.schemas.scoreboard import HeadlineCurrency, HeadlineWindow, ScoreboardHeadline


SOURCES = ("model", "persistence", "climatology", "oracle")
CURRENCIES: tuple[tuple[str, bool], ...] = (
    ("topdecile_hit", True), ("rank_spearman", True), ("sign_agree", True),
)
WINDOWS = (30, 90)


def _weighted_mean(pairs: list[tuple[float | None, float | None]]) -> float | None:
    numerator = denominator = 0.0
    for value, weight in pairs:
        if value is not None and weight:
            numerator += value * weight
            denominator += weight
    return numerator / denominator if denominator else None


def _windows(rows: list[dict], as_of: date) -> list[HeadlineWindow]:
    result: list[HeadlineWindow] = []
    for days in WINDOWS:
        window_rows = [row for row in rows if as_of - timedelta(days=days) <= row["week"] <= as_of]
        weeks = sorted({row["week"] for row in window_rows})
        currencies = []
        for name, higher_is_better in CURRENCIES:
            pooled = {source: _weighted_mean([(row[name], row["n_hours"]) for row in window_rows if row["source"] == source]) for source in SOURCES}
            model, persistence = pooled["model"], pooled["persistence"]
            currencies.append(HeadlineCurrency(currency=name, higher_is_better=higher_is_better, model=model, persistence=persistence, climatology=pooled["climatology"], oracle=pooled["oracle"], persistence_delta=None if model is None or persistence is None else model - persistence))
        result.append(HeadlineWindow(window_days=days, weeks=len(weeks), week_start=weeks[0] if weeks else as_of, week_end=weeks[-1] if weeks else as_of, currencies=currencies))
    return result


def build_headline(run_id: str | None) -> ScoreboardHeadline:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        if run_id is None:
            cur.execute("SELECT run_id FROM scoreboard_weekly ORDER BY week DESC, run_id LIMIT 1")
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=503, detail="no scoreboard board is loaded (scoreboard_weekly is empty).")
            run_id = row["run_id"]
        cur.execute("SELECT week, source, n_hours, topdecile_hit, rank_spearman, sign_agree FROM scoreboard_weekly WHERE run_id = %s AND source = ANY(%s) ORDER BY week", (run_id, list(SOURCES)))
        rows = cur.fetchall()
    if not rows:
        raise HTTPException(status_code=503, detail=f"no scoreboard_weekly rows for run_id={run_id}. Load the board first (compute.jobs.backfill_scoreboard).")
    as_of = max(row["week"] for row in rows)
    return ScoreboardHeadline(run_id=run_id, as_of_week=as_of, windows=_windows(rows, as_of))
