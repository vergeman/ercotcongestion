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
