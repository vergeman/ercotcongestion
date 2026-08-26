"""GET /ercot_range -- compact realized congestion + DAM SPP window.

It reads the DAM SPP rows once and sends settlement-point identifiers once per
response rather than once per hour and per view.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from db import get_pool
from models import ErcotRangeEntry, ErcotRangeResponse
from services.time import coerce_utc

router = APIRouter()


def _round_congestion_difference(spp: object, system_lambda: object) -> float:
    """Serve map congestion at cent resolution, avoiding float artifacts."""
    value = Decimal(str(spp)) - Decimal(str(system_lambda))
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


@router.get(
    "/ercot_range",
    response_model=ErcotRangeResponse,
    summary="Compact realized ERCOT congestion and SPP snapshots across a window",
)
def get_ercot_range(
    start: datetime = Query(..., description="ISO-8601 UTC start (inclusive)"),
    end: datetime = Query(..., description="ISO-8601 UTC end (inclusive)"),
) -> ErcotRangeResponse:
    start_u = coerce_utc(start)
    end_u = coerce_utc(end)

    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                WITH spp_rows AS (
                    SELECT DISTINCT ON (interval_ts, settlement_point)
                           interval_ts, settlement_point, dam_spp
                    FROM ercot_dam_spp
                    WHERE interval_ts >= %s AND interval_ts <= %s
                    ORDER BY interval_ts, settlement_point, dst_flag ASC
                ), lambda_rows AS (
                    SELECT DISTINCT ON (interval_ts) interval_ts, system_lambda
                    FROM dam_system_lambda
                    WHERE interval_ts >= %s AND interval_ts <= %s
                    ORDER BY interval_ts, dst_flag ASC
                )
                SELECT spp_rows.interval_ts, settlement_point, dam_spp,
                       lambda_rows.system_lambda
                FROM spp_rows
                LEFT JOIN lambda_rows USING (interval_ts)
                ORDER BY spp_rows.interval_ts, settlement_point
                """,
                (start_u, end_u, start_u, end_u),
            )
            rows = cur.fetchall()

    if not rows:
        raise HTTPException(
            status_code=503,
            detail=f"no ercot_dam_spp rows in window {start_u} .. {end_u}.",
        )

    sp_ids = sorted({str(row["settlement_point"]) for row in rows})
    sp_index = {sp_id: index for index, sp_id in enumerate(sp_ids)}
    by_ts: dict[datetime, ErcotRangeEntry] = {}
    for row in rows:
        ts = coerce_utc(row["interval_ts"])
        entry = by_ts.get(ts)
        if entry is None:
            entry = ErcotRangeEntry(
                interval_ts=ts,
                system_lambda=(
                    None
                    if row["system_lambda"] is None
                    else float(row["system_lambda"])
                ),
                congestion=[None] * len(sp_ids),
                spp=[None] * len(sp_ids),
            )
            by_ts[ts] = entry
        index = sp_index[str(row["settlement_point"])]
        spp = None if row["dam_spp"] is None else float(row["dam_spp"])
        system_lambda = row["system_lambda"]
        entry.spp[index] = spp
        entry.congestion[index] = (
            None
            if spp is None or system_lambda is None
            else _round_congestion_difference(row["dam_spp"], system_lambda)
        )

    entries = [by_ts[ts] for ts in sorted(by_ts)]
    return ErcotRangeResponse(
        start=start_u, end=end_u, count=len(entries), sp_ids=sp_ids, entries=entries
    )
