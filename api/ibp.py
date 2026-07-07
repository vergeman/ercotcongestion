"""GET /ibp/ercot — promoted implied-binding-proximity panel for one hour.

Which run_id we serve is resolved per-request from
``implied_binding_proximity_current[ercot]`` so a ``ingest --promote`` flip
is picked up on the next request without a redeploy.

Two round-trips instead of a single joined query so we can distinguish
"nothing promoted yet" (404) from "promoted run has no rows for this ts"
(200 with empty ``points``).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from db import get_pool

from models import IbpErcotPoint, IbpErcotResponse

log = logging.getLogger(__name__)

router = APIRouter()


def _coerce_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


@router.get(
    "/ibp/ercot",
    response_model=IbpErcotResponse,
    summary="Promoted bp_ercot panel for a single hour",
)
def get_ibp_ercot(
    ts: datetime = Query(..., description="ISO-8601 UTC hour"),
) -> IbpErcotResponse:
    ts_u = _coerce_utc(ts)

    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT run_id
                FROM implied_binding_proximity_current
                WHERE layer = 'ercot'
                """
            )
            pointer = cur.fetchone()
            if pointer is None:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "no implied_binding_proximity run promoted for layer "
                        "'ercot'. Run compute.implied_binding_proximity.ingest "
                        "with --promote first."
                    ),
                )
            run_id = pointer["run_id"]

            cur.execute(
                """
                SELECT settlement_point, bp
                FROM implied_binding_proximity
                WHERE ts = %s AND run_id = %s
                """,
                (ts_u, run_id),
            )
            rows = cur.fetchall()

    points = [
        IbpErcotPoint(
            settlement_point=str(r["settlement_point"]),
            bp=float(r["bp"]),
        )
        for r in rows
    ]

    return IbpErcotResponse(ts=ts_u, run_id=run_id, points=points)
