"""Realized ERCOT congestion range query service.

It reads DAM SPP rows once and sends settlement-point identifiers once per
response rather than once per hour and per view.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from psycopg.rows import dict_row

from db import get_pool
from schemas.forecast import ErcotRangeEntry, ErcotRangeResponse
from services.time import coerce_utc


def _round_congestion_difference(spp: object, system_lambda: object) -> float:
    """Serve map congestion at cent resolution, avoiding float artifacts."""
    value = Decimal(str(spp)) - Decimal(str(system_lambda))
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def ercot_range(start: datetime, end: datetime) -> ErcotRangeResponse:
    """Return realized congestion and SPP snapshots for a normalized interval."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
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
            (start, end, start, end),
        )
        rows = cur.fetchall()

    if not rows:
        raise HTTPException(status_code=503, detail=f"no ercot_dam_spp rows in window {start} .. {end}.")

    # The shared SP index keeps missing values aligned between intervals.
    sp_ids = sorted({str(row["settlement_point"]) for row in rows})
    sp_index = {sp_id: index for index, sp_id in enumerate(sp_ids)}
    by_ts: dict[datetime, ErcotRangeEntry] = {}
    for row in rows:
        ts = coerce_utc(row["interval_ts"])
        entry = by_ts.get(ts)
        if entry is None:
            entry = ErcotRangeEntry(
                interval_ts=ts,
                system_lambda=None if row["system_lambda"] is None else float(row["system_lambda"]),
                congestion=[None] * len(sp_ids),
                spp=[None] * len(sp_ids),
            )
            by_ts[ts] = entry
        index = sp_index[str(row["settlement_point"])]
        spp = None if row["dam_spp"] is None else float(row["dam_spp"])
        entry.spp[index] = spp
        entry.congestion[index] = (
            None if spp is None or row["system_lambda"] is None
            else _round_congestion_difference(row["dam_spp"], row["system_lambda"])
        )

    entries = [by_ts[ts] for ts in sorted(by_ts)]
    return ErcotRangeResponse(start=start, end=end, count=len(entries), sp_ids=sp_ids, entries=entries)
