"""Scoreboard summary builders.

The scoreboard summary is the serving slice of the self-grading track record
(plan/0102 §0001,
spec-phase3-scoreboard.md §3). Reads ``scoreboard_weekly`` (loaded by
``compute.jobs.load_scoreboard`` from the pre-registered weekly CSVs) and rolls
the trailing weeks into per-currency tiles. This is the *panel* headline — the
full weekly series, coverage strip and pre/post-RTC+B split are
the Scoreboard page (0002).

Integrity rule (spec §6): the API never serves a model number without its
comparators. Every currency in every window carries ``persistence`` (with the
``model - persistence`` delta), ``climatology``, and the ``oracle`` ceiling, so
the client physically cannot render a lone model figure.

The builders select the most recent board present (max ``week``), independent of
the forecast pointer, since a board's ``run_id`` lives in its own namespace.
They raise 503 when their source data is unavailable; the summary represents
that as a typed unavailable section.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from fastapi import APIRouter, HTTPException
from psycopg.rows import dict_row

from db import get_pool
from schemas.common import BootstrapSectionStatus
from schemas.scoreboard import (
    DailyPoint,
    ScoreboardDaily,
    ScoreboardHeadline,
    ScoreboardHistory,
    ScoreboardSummaryResponse,
    ScoreboardWeekly,
    ScoreHistoryPoint,
    SourcePooled,
    WeeklyPoint,
    WeeklySplit,
)
from services.bootstrap import availability_status, soft_fail
from services.scoreboard_headline import build_headline

log = logging.getLogger(__name__)

router = APIRouter()


# The comparators that ride with every model figure (spec §6). Ordered model-first
# so the client reads model → its delta → the ceiling.
_SOURCES = ("model", "persistence", "climatology", "oracle")

# The RTC+B structural break (compute.evaluation.mu.RTC_B) — pooled stats are split on
# it so the post-cutover number can't be laundered into the pooled figure (§5).
RTC_B_CUTOVER = date(2025, 12, 5)

# The screening currencies pooled into each split summary.
_POOL_METRICS = ("rank_spearman", "sign_agree", "topdecile_hit")
def _resolve_weekly_run_id(cur) -> str:
    """Resolve the most recent board (max week).
    Raises 503 when scoreboard_weekly is empty (no board loaded), matching the
    realized ranges' soft-fail contract."""
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
    """Plain week-mean over non-NULL cells — the reduction r5()/cell() uses, so a
    served pooled figure equals the pre-registered readout. None if no scored week
    (a currency the source never scored, e.g. the null source's declined topdec)."""
    vals = [r[key] for r in rows if r[key] is not None]
    return sum(vals) / len(vals) if vals else None


def _pooled_source(rows: list[dict], source: str) -> SourcePooled:
    src_rows = [r for r in rows if r["source"] == source]
    return SourcePooled(
        source=source,
        **{k: _mean(src_rows, k) for k in _POOL_METRICS},
    )


def _build_splits(rows: list[dict]) -> list[WeeklySplit]:
    """The pooled all / pre-RTC+B / post-RTC+B slices (§5)."""
    from compute.jobs.backfill_nodal import existence_test

    slices = [
        ("all", rows),
        ("pre_rtc_b", [r for r in rows if r["week"] < RTC_B_CUTOVER]),
        ("post_rtc_b", [r for r in rows if r["week"] >= RTC_B_CUTOVER]),
    ]
    splits: list[WeeklySplit] = []
    for label, slice_rows in slices:
        pooled = {s: _pooled_source(slice_rows, s) for s in _SOURCES}
        m = pooled["model"]
        p = pooled["persistence"]

        beats: bool | None = None
        if (
            m.rank_spearman is not None
            and m.sign_agree is not None
            and m.topdecile_hit is not None
        ):
            keys = ("rank_spearman", "sign_agree", "topdecile_hit")
            if all(getattr(p, k) is not None for k in keys):
                beats, _ = existence_test(
                    {k: getattr(m, k) for k in keys},
                    {k: getattr(p, k) for k in keys},
                )

        splits.append(
            WeeklySplit(
                label=label,
                n_weeks=len({r["week"] for r in slice_rows}),
                sources=[pooled[s] for s in _SOURCES],
                beats_persistence=beats,
            )
        )
    return splits


def build_scoreboard_weekly() -> ScoreboardWeekly:
    """Build the weekly section embedded in ``/scoreboard/summary``."""
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            run_id = _resolve_weekly_run_id(cur)
            # All sources — the chart draws model + baselines +
            # oracle, and the summary pools them. Ordered (week, source) for the
            # series.
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
                "Load the board first (compute.jobs.load_scoreboard)."
            ),
        )

    points = [WeeklyPoint(**r) for r in rows]
    return ScoreboardWeekly(
        run_id=run_id,
        primary_source="model",
        rtc_b_cutover=RTC_B_CUTOVER,
        points=points,
        splits=_build_splits(rows),
    )


# --------------------------------------------------------------------------
# Latest final live grade — an internal section of /scoreboard/summary
# --------------------------------------------------------------------------

def _resolve_latest_final_daily_run_id(cur) -> str:
    """Resolve the run containing the newest final served grade."""
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
    """Build the newest fully persisted final grade and all comparator rows."""
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            run_id = _resolve_latest_final_daily_run_id(cur)
            # Every source for the run — the page draws model + baselines + oracle +
            # the null tripwire; a lone model figure can't be rendered (spec §6).
            sql = (
                "SELECT delivery_date, source, horizon, rank_spearman, sign_agree, "
                "topdecile_hit, "
                "sf_coverage, model_coverage, n_hours, n_nodes "
                "FROM scoreboard_daily WHERE run_id = %s AND horizon = %s"
            )
            params: list[object] = [run_id, 1, run_id]
            sql += (
                " AND delivery_date = (SELECT max(delivery_date) "
                "FROM scoreboard_daily WHERE run_id = %s AND horizon = 1)"
            )
            sql += " ORDER BY delivery_date, source"
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()

    if not rows:
        raise HTTPException(
            status_code=503,
            detail=(
                f"no final scoreboard_daily rows for run_id={run_id}. "
                "Grade a served day first (compute.jobs.grade_day)."
            ),
        )

    return ScoreboardDaily(
        run_id=run_id,
        primary_source="model",
        horizon=1,
        selected_delivery_date=rows[0]["delivery_date"],
        points=[DailyPoint(**r) for r in rows],
    )


# --------------------------------------------------------------------------
# Scoreboard history — an internal section of /scoreboard/summary
# --------------------------------------------------------------------------

def build_scoreboard_history(weekly: ScoreboardWeekly) -> ScoreboardHistory:
    """Append final served grades to an already-resolved weekly board.

    The live tail intentionally queries horizon 1 directly. Missing live grades
    are an empty tail, not a failure of the backtest chart.
    """
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
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
        ScoreHistoryPoint(cadence="served_daily", **row)
        for row in daily_rows
    )
    boundary_date = min((row["delivery_date"] for row in daily_rows), default=None)
    return ScoreboardHistory(
        primary_source=weekly.primary_source,
        weekly_run_id=weekly.run_id,
        daily_run_id=daily_run_id,
        boundary_date=boundary_date,
        points=points,
    )


# --------------------------------------------------------------------------
# /scoreboard/summary — the Scoreboard page's load-time sections in one call
# --------------------------------------------------------------------------

@router.get(
    "/scoreboard/summary",
    response_model=ScoreboardSummaryResponse,
    summary="One bundled payload for the Scoreboard page summary (0137)",
)
def get_scoreboard_summary(
) -> ScoreboardSummaryResponse:
    """Compose the Scoreboard's load-time sections behind one call.

    ``weekly``/``headline`` both resolve their own latest ``run_id`` from
    ``scoreboard_weekly``; ``daily`` resolves independently from the separate
    ``scoreboard_daily`` live board. Unlike the Brief's per-day sections, these
    are not forced onto one shared run — that already-independent resolution
    is exactly what today's three separate requests do, so this composition
    preserves it rather than unifying it. ``history`` reuses the resolved
    weekly section and independently resolves only final live grades.

    The three internal section builders run concurrently; history then reuses
    the weekly result.
    """
    with ThreadPoolExecutor(max_workers=3) as pool:
        weekly = pool.submit(soft_fail, build_scoreboard_weekly)
        headline = pool.submit(soft_fail, lambda: build_headline(None))
        daily = pool.submit(soft_fail, build_latest_final_daily)
        weekly_result = weekly.result()
        headline_result = headline.result()
        daily_result = daily.result()
        history_result = (
            soft_fail(lambda: build_scoreboard_history(weekly_result))
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
