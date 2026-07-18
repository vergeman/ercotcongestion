"""GET /ercot_state_range — per-hour ERCOT SP congestion for a window.

Congestion is ``SPP − system_λ`` computed from the DB at request time: the
published DAM SPP (``ercot_dam_spp``, NP4-190-CD) minus the day-ahead system
lambda (``dam_system_lambda``, NP4-523-CD), the distributed-slack reference
the map + implied-SF fit use. This mirrors
``compute.sf.panels.load_congestion_panel(ref_method="system_lambda")`` and
reads the same tables ``/ercot_spp_range`` does — no run artifact, no
served-run pointer.

Both feeds can carry duplicate ``(interval_ts, …)`` rows (one per DST-flag
variant); we collapse with ``DISTINCT ON`` keeping the ``dst_flag = FALSE``
variant first, matching ``/ercot_spp_range`` and the congestion panel.

An empty window returns 503 rather than synthesising values (the client maps
503 → null).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from db import get_pool

from models import ErcotSpState, ErcotStateRangeEntry, ErcotStateRangeResponse

log = logging.getLogger(__name__)

router = APIRouter()


def _coerce_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


@router.get(
    "/ercot_state_range",
    response_model=ErcotStateRangeResponse,
    summary="ERCOT SP congestion snapshots across a window",
)
def get_ercot_state_range(
    start: datetime = Query(..., description="ISO-8601 UTC start (inclusive)"),
    end: datetime = Query(..., description="ISO-8601 UTC end (inclusive)"),
) -> ErcotStateRangeResponse:
    start_u = _coerce_utc(start)
    end_u = _coerce_utc(end)

    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (interval_ts) interval_ts, system_lambda
                FROM dam_system_lambda
                WHERE interval_ts >= %s AND interval_ts <= %s
                ORDER BY interval_ts, dst_flag ASC
                """,
                (start_u, end_u),
            )
            lam_rows = cur.fetchall()

            cur.execute(
                """
                SELECT DISTINCT ON (interval_ts, settlement_point)
                       interval_ts, settlement_point, dam_spp
                FROM ercot_dam_spp
                WHERE interval_ts >= %s AND interval_ts <= %s
                ORDER BY interval_ts, settlement_point, dst_flag ASC
                """,
                (start_u, end_u),
            )
            spp_rows = cur.fetchall()

    lam_by_ts: dict[datetime, float | None] = {
        _coerce_utc(r["interval_ts"]): (
            None if r["system_lambda"] is None else float(r["system_lambda"])
        )
        for r in lam_rows
    }

    # Congestion needs both a price and a reference at the same hour; an hour
    # with SPP but no system_λ (or vice versa) drops out, exactly as the panel
    # join does.
    by_ts: dict[datetime, list[ErcotSpState]] = {}
    for r in spp_rows:
        ts = _coerce_utc(r["interval_ts"])
        lam = lam_by_ts.get(ts)
        if lam is None:
            continue
        spp = r["dam_spp"]
        congestion = None if spp is None else float(spp) - lam
        by_ts.setdefault(ts, []).append(
            ErcotSpState(
                sp_id=str(r["settlement_point"]),
                congestion=congestion,
            )
        )

    if not by_ts:
        raise HTTPException(
            status_code=503,
            detail=(
                f"no congestion computable in window {start_u} .. {end_u} "
                f"(need overlapping ercot_dam_spp and dam_system_lambda rows)."
            ),
        )

    entries = [
        ErcotStateRangeEntry(interval_ts=ts, sps=sps)
        for ts, sps in sorted(by_ts.items())
    ]

    return ErcotStateRangeResponse(
        start=start_u,
        end=end_u,
        count=len(entries),
        entries=entries,
    )
