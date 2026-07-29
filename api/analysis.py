"""GET /analysis/brief — the server-computed daily Insight Brief.

Read-only surface over ``analysis_brief`` (0124): the daily_brief job computes
one JSON brief per (run_id, delivery_date, horizon) from the served SF+μ̂
artifact; this endpoint hands it back verbatim. The disabled Analysis nav item
is its home (docs/last_mile.md). Nothing is computed here — a day with no brief
yet returns ``available=false`` rather than 404, matching the Matrix's soft-fail
contract so the UI can render an empty state.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from db import get_pool

router = APIRouter(prefix="/analysis")


@router.get("/brief", summary="Server-computed daily Insight Brief")
def get_brief(
    delivery_date: date = Query(..., description="Delivery day (UTC calendar date)."),
    run_id: str | None = Query(None, description="Model version; defaults to the "
                               "currently published ercot run."),
    horizon: int | None = Query(None, ge=1, le=2, description="Artifact track; "
                                "defaults to the served horizon (final, else preview)."),
) -> dict:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        if run_id is None:
            cur.execute("SELECT run_id FROM forecast_current WHERE layer = 'ercot'")
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=503, detail="no forecast run is published yet.")
            run_id = str(row["run_id"])

        # Coalesce the horizon the same way the artifact lookup does: serve the
        # final brief when one exists, else the preview.
        if horizon is None:
            cur.execute(
                "SELECT min(horizon) AS h FROM analysis_brief "
                "WHERE run_id = %s AND delivery_date = %s",
                (run_id, delivery_date),
            )
            row = cur.fetchone()
            if row is None or row["h"] is None:
                return {"available": False, "unavailable_reason": "brief_missing",
                        "run_id": run_id, "delivery_date": delivery_date}
            horizon = int(row["h"])

        cur.execute(
            "SELECT brief, horizon, computed_at FROM analysis_brief "
            "WHERE run_id = %s AND delivery_date = %s AND horizon = %s",
            (run_id, delivery_date, horizon),
        )
        row = cur.fetchone()

    if row is None:
        return {"available": False, "unavailable_reason": "brief_missing",
                "run_id": run_id, "delivery_date": delivery_date, "horizon": horizon}

    return {
        "available": True,
        "run_id": run_id,
        "delivery_date": delivery_date,
        "horizon": int(row["horizon"]),
        "computed_at": row["computed_at"],
        "brief": row["brief"],
    }


@router.get("/brief/latest", summary="Latest day's Insight Brief + the day index")
def get_brief_latest(
    run_id: str | None = Query(None, description="Model version; defaults to the "
                               "currently published ercot run."),
) -> dict:
    """The most recent day's full brief, plus the run's ``available_dates`` index.

    Resolves the run the same way ``GET /analysis/brief`` does, picks the latest
    ``delivery_date`` that has a brief, and returns that day's brief in the same
    envelope the per-day endpoint uses — coalescing the served horizon (final,
    else preview) exactly as the sibling does. ``available_dates`` is the sorted
    list of every delivery day with a brief for the run: the page derives prev/next
    as array neighbors (gaps skipped) and fetches each day through the frozen
    per-day endpoint. ``available=false`` (not 404) when the run has no brief yet.
    """
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        if run_id is None:
            cur.execute("SELECT run_id FROM forecast_current WHERE layer = 'ercot'")
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=503, detail="no forecast run is published yet.")
            run_id = str(row["run_id"])

        # The run's day index (dates only — cheap). Neighbors of this sorted list
        # are what the page steps through, so gaps in history are skipped.
        cur.execute(
            "SELECT DISTINCT delivery_date FROM analysis_brief "
            "WHERE run_id = %s ORDER BY delivery_date",
            (run_id,),
        )
        available_dates = [r["delivery_date"] for r in cur.fetchall()]
        if not available_dates:
            return {"available": False, "unavailable_reason": "brief_missing",
                    "run_id": run_id, "available_dates": []}

        delivery_date = available_dates[-1]

        # Coalesce the served horizon for the latest day: final (min horizon) wins.
        cur.execute(
            "SELECT brief, horizon, computed_at FROM analysis_brief "
            "WHERE run_id = %s AND delivery_date = %s ORDER BY horizon LIMIT 1",
            (run_id, delivery_date),
        )
        row = cur.fetchone()

    return {
        "available": True,
        "run_id": run_id,
        "delivery_date": delivery_date,
        "horizon": int(row["horizon"]),
        "computed_at": row["computed_at"],
        "brief": row["brief"],
        "available_dates": available_dates,
    }
