"""GET /scoreboard/headline — the rolling backtest headline (30/90-day tiles).

The thin serving slice of the self-grading track record (plan/0102 §0001,
spec-phase3-scoreboard.md §3). Reads ``scoreboard_weekly`` (loaded by
``compute.jobs.load_scoreboard`` from the pre-registered weekly CSVs) and rolls
the trailing weeks into per-currency tiles. This is the *panel* headline — the
full weekly series, regime selector, coverage strip and pre/post-RTC+B split are
the scoreboard page (0002), not here.

Integrity rule (spec §6): the API never serves a model number without its
comparators. Every currency in every window carries ``persistence`` (with the
``model - persistence`` delta), ``climatology``, and the ``oracle`` ceiling, so
the client physically cannot render a lone model figure.

``run_id`` names the model version whose backtest is served. Omit it and the
endpoint serves the most recent board present (max ``week``) — this feature's own
default, independent of the forecast pointer, since a board's ``run_id`` lives in
its own namespace. 503 (not empty) when no board is loaded / the regime has no
rows, matching the realized ranges' soft-fail contract.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from db import get_pool
from models import HeadlineCurrency, HeadlineWindow, ScoreboardHeadline

log = logging.getLogger(__name__)

router = APIRouter()

# The comparators that ride with every model figure (spec §6). Ordered model-first
# so the client reads model → its delta → the ceiling.
_SOURCES = ("model", "persistence", "climatology", "oracle")

# The headline currencies and their orientation. Screening currencies lead
# (top-decile / rank / sign); pooled_r2 rides along as the magnitude diagnostic.
# All four are higher-is-better, so a positive persistence delta is the model
# winning. mae (lower-is-better magnitude) is deliberately left to the full board.
_CURRENCIES: tuple[tuple[str, bool], ...] = (
    ("topdecile_hit", True),
    ("rank_spearman", True),
    ("sign_agree", True),
    ("pooled_r2", True),
)

# Trailing windows, in days. Weekly rows land ~7 days apart, so 30d ≈ 4–5 weeks
# and 90d ≈ 13 weeks.
_WINDOWS = (30, 90)


def _wmean(pairs: list[tuple[float | None, float | None]]) -> float | None:
    """n_hours-weighted mean, skipping NULL values / weights. None if nothing to
    pool — so a currency a source never scored in the window comes back None
    rather than 0 (a flat/declined cell must not read as a real score, §6)."""
    num = 0.0
    den = 0.0
    for value, weight in pairs:
        if value is None or not weight:
            continue
        num += value * weight
        den += weight
    return num / den if den else None


def _build_windows(rows: list[dict], as_of: date) -> list[HeadlineWindow]:
    """Roll the weekly rows into the trailing 30/90-day tiles."""
    windows: list[HeadlineWindow] = []
    for wdays in _WINDOWS:
        lo = as_of - timedelta(days=wdays)
        in_window = [r for r in rows if lo <= r["week"] <= as_of]
        weeks = sorted({r["week"] for r in in_window})

        currencies: list[HeadlineCurrency] = []
        for name, higher in _CURRENCIES:
            # Pool each source separately over its own weekly cells + n_hours.
            pooled: dict[str, float | None] = {}
            for src in _SOURCES:
                pooled[src] = _wmean(
                    [(r[name], r["n_hours"]) for r in in_window if r["source"] == src]
                )
            model = pooled["model"]
            persistence = pooled["persistence"]
            delta = (
                model - persistence
                if model is not None and persistence is not None
                else None
            )
            currencies.append(
                HeadlineCurrency(
                    currency=name,
                    higher_is_better=higher,
                    model=model,
                    persistence=persistence,
                    climatology=pooled["climatology"],
                    oracle=pooled["oracle"],
                    persistence_delta=delta,
                )
            )

        windows.append(
            HeadlineWindow(
                window_days=wdays,
                weeks=len(weeks),
                week_start=weeks[0] if weeks else as_of,
                week_end=weeks[-1] if weeks else as_of,
                currencies=currencies,
            )
        )
    return windows


@router.get(
    "/scoreboard/headline",
    response_model=ScoreboardHeadline,
    summary="Rolling 30/90-day backtest headline — model with its persistence "
    "delta and oracle ceiling, per currency",
)
def get_scoreboard_headline(
    run_id: str | None = Query(
        None,
        description="Board (model version) to serve. Omit for the most recent "
        "board present in scoreboard_weekly.",
    ),
    regime: str = Query(
        "all",
        description="Regime slice — `all` or a net-load quintile / named regime.",
    ),
) -> ScoreboardHeadline:
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            # Resolve the board: an explicit ?run_id= wins; otherwise the most
            # recent board (max week). 503 when the table is empty (no board
            # loaded), so the client renders the panel without the scorecard.
            if run_id is None:
                cur.execute(
                    "SELECT run_id FROM scoreboard_weekly "
                    "ORDER BY week DESC, run_id LIMIT 1"
                )
                row = cur.fetchone()
                if row is None:
                    raise HTTPException(
                        status_code=503,
                        detail="no scoreboard board is loaded "
                        "(scoreboard_weekly is empty).",
                    )
                run_id = row["run_id"]
            assert run_id is not None  # resolved from param or table above

            cur.execute(
                """
                SELECT week, source, n_hours,
                       topdecile_hit, rank_spearman, sign_agree, pooled_r2
                FROM scoreboard_weekly
                WHERE run_id = %s AND regime = %s AND source = ANY(%s)
                ORDER BY week
                """,
                (run_id, regime, list(_SOURCES)),
            )
            rows = cur.fetchall()

    if not rows:
        raise HTTPException(
            status_code=503,
            detail=(
                f"no scoreboard_weekly rows for run_id={run_id} regime={regime}. "
                "Load the board first (compute.jobs.load_scoreboard)."
            ),
        )

    as_of = max(r["week"] for r in rows)
    return ScoreboardHeadline(
        run_id=run_id,
        regime=regime,
        as_of_week=as_of,
        windows=_build_windows(rows, as_of),
    )
