"""GET /ercot_spp_range — raw DAM SPP per settlement point for a window.

Reads ``ercot_dam_spp`` (NP4-190-CD) directly rather than the congestion
matrix, since the LMP palette wants the published $/MWh prices, not the
system_λ-shifted congestion component.

Rows in `ercot_dam_spp` can carry duplicate (interval_ts, settlement_point)
entries — the same SP appears once per DST-flag variant. We collapse with
``DISTINCT ON`` keeping the ``dst_flag = FALSE`` variant first, matching
the same collapse used by ``compute.ercot.transforms.fetch_dam_spp_batch``.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from db import get_pool

from models import (
    ErcotSpSpp,
    ErcotSppRangeEntry,
    ErcotSppRangeResponse,
)

log = logging.getLogger(__name__)

router = APIRouter()


def _coerce_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


@router.get(
    "/ercot_spp_range",
    response_model=ErcotSppRangeResponse,
    summary="Raw DAM SPP per settlement point across a window",
)
def get_ercot_spp_range(
    start: datetime = Query(..., description="ISO-8601 UTC start (inclusive)"),
    end: datetime = Query(..., description="ISO-8601 UTC end (inclusive)"),
) -> ErcotSppRangeResponse:
    start_u = _coerce_utc(start)
    end_u = _coerce_utc(end)

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
                ), load_rows AS (
                    SELECT DISTINCT ON (interval_ts) interval_ts, total
                    FROM load_by_zone
                    WHERE interval_ts >= %s AND interval_ts <= %s
                    ORDER BY interval_ts, dst_flag ASC
                )
                SELECT spp_rows.interval_ts, settlement_point, dam_spp,
                       load_rows.total AS total_load_mw
                FROM spp_rows
                LEFT JOIN load_rows USING (interval_ts)
                ORDER BY spp_rows.interval_ts, settlement_point
                """,
                (start_u, end_u, start_u, end_u),
            )
            rows = cur.fetchall()

    if not rows:
        raise HTTPException(
            status_code=503,
            detail=(
                f"no ercot_dam_spp rows in window {start_u} .. {end_u}. "
                "Ingest DAM SPP first."
            ),
        )

    by_ts: dict[datetime, tuple[float | None, list[ErcotSpSpp]]] = {}
    for r in rows:
        ts = _coerce_utc(r["interval_ts"])
        spp = r["dam_spp"]
        total_load = r["total_load_mw"]
        load, sps = by_ts.setdefault(
            ts, (None if total_load is None else float(total_load), [])
        )
        sps.append(
            ErcotSpSpp(
                sp_id=str(r["settlement_point"]),
                spp=None if spp is None else float(spp),
            )
        )

    entries = [
        ErcotSppRangeEntry(interval_ts=ts, total_load_mw=load, sps=sps)
        for ts, (load, sps) in sorted(by_ts.items())
    ]

    return ErcotSppRangeResponse(
        start=start_u,
        end=end_u,
        count=len(entries),
        entries=entries,
    )
