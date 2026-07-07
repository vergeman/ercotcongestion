"""GET /ibp/ercot — promoted implied-binding-proximity panel for one hour.

Which run_id we serve is resolved per-request from
``implied_binding_proximity_current[ercot]`` so a ``ingest --promote`` flip
is picked up on the next request without a redeploy.

Two round-trips instead of a single joined query so we can distinguish
"nothing promoted yet" (404) from "promoted run has no rows for this ts"
(200 with empty ``points``).

The range sibling ``GET /ibp/ercot_range`` follows the same pointer→panel
pattern but soft-fails with 503 (matching /ercot_spp_range) so the client
can render the model pane alone when nothing is promoted.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from db import get_pool

from models import (
    IbpErcotPoint,
    IbpErcotRangeEntry,
    IbpErcotRangeResponse,
    IbpErcotResponse,
)

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


@router.get(
    "/ibp/ercot_range",
    response_model=IbpErcotRangeResponse,
    summary="Promoted bp_ercot panel across a window",
)
def get_ibp_ercot_range(
    start: datetime = Query(..., description="ISO-8601 UTC start (inclusive)"),
    end: datetime = Query(..., description="ISO-8601 UTC end (inclusive)"),
) -> IbpErcotRangeResponse:
    start_u = _coerce_utc(start)
    end_u = _coerce_utc(end)

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
                # 503 (not 404) mirrors the /ercot_spp_range soft-fail:
                # client interprets it as "backend artifact not built" and
                # renders the model pane alone.
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "no implied_binding_proximity run promoted for layer "
                        "'ercot'. Run compute.implied_binding_proximity.ingest "
                        "with --promote first."
                    ),
                )
            run_id = pointer["run_id"]

            cur.execute(
                """
                SELECT ts, settlement_point, bp
                FROM implied_binding_proximity
                WHERE run_id = %s AND ts BETWEEN %s AND %s
                """,
                (run_id, start_u, end_u),
            )
            rows = cur.fetchall()

    if not rows:
        raise HTTPException(
            status_code=503,
            detail=(
                f"no implied_binding_proximity rows in window "
                f"{start_u} .. {end_u} for run_id {run_id}."
            ),
        )

    by_ts: dict[datetime, list[IbpErcotPoint]] = {}
    for r in rows:
        ts = _coerce_utc(r["ts"])
        by_ts.setdefault(ts, []).append(
            IbpErcotPoint(
                settlement_point=str(r["settlement_point"]),
                bp=float(r["bp"]),
            )
        )

    # Enumerate hourly slots in the window and synthesize empty entries for
    # hours the promoted run didn't cover. Client's per-hour cache lookup
    # then sees `{points: []}` (data known-empty) rather than "no entry"
    # (data missing) — matches /ibp/ercot's per-hour empty-points contract.
    start_hour = start_u.replace(minute=0, second=0, microsecond=0)
    end_hour = end_u.replace(minute=0, second=0, microsecond=0)
    entries: list[IbpErcotRangeEntry] = []
    slot = start_hour
    while slot <= end_hour:
        entries.append(
            IbpErcotRangeEntry(
                interval_ts=slot,
                points=by_ts.get(slot, []),
            )
        )
        slot += timedelta(hours=1)

    return IbpErcotRangeResponse(
        start=start_u,
        end=end_u,
        count=len(entries),
        run_id=run_id,
        entries=entries,
    )
