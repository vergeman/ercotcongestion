"""GET /scoreboard/headline — the rolling backtest headline (30/90-day tiles).

The thin serving slice of the self-grading track record (plan/0102 §0001,
spec-phase3-scoreboard.md §3). Reads ``scoreboard_weekly`` (loaded by
``compute.jobs.load_scoreboard`` from the pre-registered weekly CSVs) and rolls
the trailing weeks into per-currency tiles. This is the *panel* headline — the
full weekly series, coverage strip and pre/post-RTC+B split are
the scoreboard page (0002), not here.

Integrity rule (spec §6): the API never serves a model number without its
comparators. Every currency in every window carries ``persistence`` (with the
``model - persistence`` delta), ``climatology``, and the ``oracle`` ceiling, so
the client physically cannot render a lone model figure.

``run_id`` names the model version whose backtest is served. Omit it and the
endpoint serves the most recent board present (max ``week``) — this feature's own
default, independent of the forecast pointer, since a board's ``run_id`` lives in
its own namespace. 503 (not empty) when no board is loaded, matching the
realized ranges' soft-fail contract.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.rows import dict_row

from db import get_pool
from dependencies import server_selected_run as _server_selected_run
from schemas.common import BootstrapSectionStatus
from schemas.scoreboard import (
    DailyPoint,
    ScoreboardDaily,
    ScoreboardHeadline,
    ScoreboardSummaryResponse,
    ScoreboardWeekly,
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
def _resolve_run_id(cur, run_id: str | None) -> str:
    """Resolve the most recent board (max week).
    Raises 503 when scoreboard_weekly is empty (no board loaded), matching the
    realized ranges' soft-fail contract."""
    if run_id is not None:
        return run_id
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


@router.get(
    "/scoreboard/headline",
    response_model=ScoreboardHeadline,
    summary="Rolling 30/90-day backtest headline — model with its persistence "
    "delta and oracle ceiling, per currency",
)
def get_scoreboard_headline(
    run_id: str | None = Depends(_server_selected_run),
) -> ScoreboardHeadline:
    return build_headline(run_id)


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


@router.get(
    "/scoreboard/weekly",
    response_model=ScoreboardWeekly,
    summary="Weekly backtest series (all sources) + pooled pre/post-RTC+B summary",
)
def get_scoreboard_weekly(
    source: str = Query(
        "model",
        description="The series the page foregrounds. Comparators (persistence / "
        "climatology / oracle) ride along regardless — never a lone model figure.",
    ),
    run_id: str | None = Depends(_server_selected_run),
) -> ScoreboardWeekly:
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            run_id = _resolve_run_id(cur, run_id)
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
        primary_source=source,
        rtc_b_cutover=RTC_B_CUTOVER,
        points=points,
        splits=_build_splits(rows),
    )


# --------------------------------------------------------------------------
# /scoreboard/daily — the LIVE per-delivery-day board (0003-live-grading)
# --------------------------------------------------------------------------

def _resolve_daily_run_id(cur, run_id: str | None) -> str:
    """Resolve the run with the most recent graded day.
    Raises 503 when scoreboard_daily is empty (no live grade has run yet),
    matching the realized ranges' soft-fail contract — the client renders the
    backtest board / realized pane alone rather than erroring."""
    if run_id is not None:
        return run_id
    cur.execute(
        "SELECT run_id FROM scoreboard_daily ORDER BY delivery_date DESC, run_id "
        "LIMIT 1"
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(
            status_code=503,
            detail="no live grades yet (scoreboard_daily is empty).",
        )
    return row["run_id"]


def _resolve_daily_horizon(cur, run_id: str, horizon: int | None) -> tuple[int, list[int]]:
    """The horizon to serve, plus every horizon this run has graded.

    `scoreboard_daily` is keyed per horizon, and has carried two tracks since the
    preview cron began grading. A query without a horizon predicate therefore
    returns *two* rows per (delivery_date, source) — a final grade and a preview
    grade — which a client keying by source alone silently collapses to whichever
    arrived last. One board serves one horizon; h1 (the final forecast) is the
    default because it is what was actually served for D.

    An unknown or ungraded horizon returns no rows and falls through to the
    caller's existing 503, rather than inventing a second failure mode.
    """
    cur.execute(
        "SELECT DISTINCT horizon FROM scoreboard_daily WHERE run_id = %s "
        "ORDER BY horizon",
        (run_id,),
    )
    available = [int(r["horizon"] if isinstance(r, dict) else r[0])
                 for r in cur.fetchall()]
    if horizon is not None:
        return horizon, available
    return (1 if 1 in available else (available[0] if available else 1)), available


@router.get(
    "/scoreboard/daily",
    response_model=ScoreboardDaily,
    summary="Live per-delivery-day grades of the served forecast — model with its "
    "baselines + oracle (and the null tripwire), since a date, for one horizon",
)
def get_scoreboard_daily(
    since: date | None = Query(
        None,
        description="Earliest delivery_date to serve (inclusive). Omit for the "
        "run's full live history.",
    ),
    horizon: int | None = Query(
        None,
        ge=1,
        le=2,
        description="Forecast track to grade: 1 = final (fires D−1), 2 = preview "
        "(fires D−2). Omit for the final track when it is present. Mixing the two "
        "in one series would compare a forecast against a differently-informed "
        "forecast.",
    ),
    source: str = Query(
        "model",
        description="The series the page foregrounds. Comparators (persistence / "
        "climatology / oracle / null) ride along regardless — never a lone model "
        "figure.",
    ),
    run_id: str | None = Depends(_server_selected_run),
) -> ScoreboardDaily:
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            run_id = _resolve_daily_run_id(cur, run_id)
            horizon, horizons = _resolve_daily_horizon(cur, run_id, horizon)
            # Every source for the run — the page draws model + baselines + oracle +
            # the null tripwire; a lone model figure can't be rendered (spec §6).
            sql = (
                "SELECT delivery_date, source, horizon, rank_spearman, sign_agree, "
                "topdecile_hit, "
                "sf_coverage, model_coverage, n_hours, n_nodes "
                "FROM scoreboard_daily WHERE run_id = %s AND horizon = %s"
            )
            params: list[object] = [run_id, horizon]
            if since is not None:
                sql += " AND delivery_date >= %s"
                params.append(since)
            sql += " ORDER BY delivery_date, source"
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()

    if not rows:
        raise HTTPException(
            status_code=503,
            detail=(
                f"no scoreboard_daily rows for run_id={run_id} horizon={horizon}"
                + (f" since {since}" if since else "")
                + ". Grade a served day first (compute.jobs.grade_day)."
            ),
        )

    return ScoreboardDaily(
        run_id=run_id,
        since=since,
        primary_source=source,
        horizon=horizon,
        horizons=horizons,
        points=[DailyPoint(**r) for r in rows],
    )


# --------------------------------------------------------------------------
# /scoreboard/summary — the Scoreboard page's load-time trio in one call (0137)
# --------------------------------------------------------------------------

@router.get(
    "/scoreboard/summary",
    response_model=ScoreboardSummaryResponse,
    summary="One bundled payload for the Scoreboard page summary (0137)",
)
def get_scoreboard_summary(
    horizon: int | None = Query(
        None,
        ge=1,
        le=2,
        description="Forecast track for the live board only (the backtest sections "
        "have no horizon). Omit for the final track.",
    ),
) -> ScoreboardSummaryResponse:
    """Compose the Scoreboard's three load-time requests behind one call.

    ``weekly``/``headline`` both resolve their own latest ``run_id`` from
    ``scoreboard_weekly``; ``daily`` resolves independently from the separate
    ``scoreboard_daily`` live board. Unlike the Brief's per-day sections, these
    are not forced onto one shared run — that already-independent resolution
    is exactly what today's three separate requests do, so this composition
    preserves it rather than unifying it.

    Each handler is called directly as a plain function, bypassing FastAPI's
    request-time dependency injection, so every parameter is passed an
    explicit literal (see ``get_brief_day``'s docstring for why) — and the
    three run on a thread pool so one slow section can't serialize behind
    another.
    """
    with ThreadPoolExecutor(max_workers=3) as pool:
        weekly = pool.submit(soft_fail, lambda: get_scoreboard_weekly("model", None))
        headline = pool.submit(soft_fail, lambda: get_scoreboard_headline(None))
        daily = pool.submit(soft_fail, lambda: get_scoreboard_daily(None, horizon, "model", None))
        weekly_result = weekly.result()
        headline_result = headline.result()
        daily_result = daily.result()
        return ScoreboardSummaryResponse(
            weekly=weekly_result,
            headline=headline_result,
            daily=daily_result,
            availability={
                "weekly": availability_status(weekly_result, BootstrapSectionStatus),
                "headline": availability_status(headline_result, BootstrapSectionStatus),
                "daily": availability_status(daily_result, BootstrapSectionStatus),
            },
        )
