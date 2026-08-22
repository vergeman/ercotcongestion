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
    summary="Deprecated: use /ercot_range for realized SPP snapshots",
    deprecated=True,
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
                SELECT DISTINCT ON (interval_ts, settlement_point)
                       interval_ts, settlement_point, dam_spp
                FROM ercot_dam_spp
                WHERE interval_ts >= %s AND interval_ts <= %s
                ORDER BY interval_ts, settlement_point, dst_flag ASC
                """,
                (start_u, end_u),
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

    by_ts: dict[datetime, list[ErcotSpSpp]] = {}
    for r in rows:
        ts = _coerce_utc(r["interval_ts"])
        spp = r["dam_spp"]
        sps = by_ts.setdefault(ts, [])
        sps.append(
            ErcotSpSpp(
                sp_id=str(r["settlement_point"]),
                spp=None if spp is None else float(spp),
            )
        )

    entries = [
        ErcotSppRangeEntry(interval_ts=ts, sps=sps)
        for ts, sps in sorted(by_ts.items())
    ]

    return ErcotSppRangeResponse(
        start=start_u,
        end=end_u,
        count=len(entries),
        entries=entries,
    )
