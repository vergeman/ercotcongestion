"""GET /api/state and GET /api/state_range.

state         : single timestamp, returns meta + per-bus values
state_range   : timestamp range, returns same shape per snapshot (capped)

Uses psycopg's dict_row factory so rows arrive as dicts and splat directly
into Pydantic models — no manual column unpacking. Column lists below are
written to match the field names on SnapshotMeta and BusState exactly.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from config import MAX_STATE_RANGE_HOURS
from db import get_pool

from models import (
    BusState,
    SnapshotMeta,
    StateRangeEntry,
    StateRangeResponse,
    StateResponse,
)

router = APIRouter()


# Column list aliased to match SnapshotMeta field names.
# Just wildcard for now, no distinction.
META_COLS = """*"""


def _coerce_utc(ts: datetime) -> datetime:
    """FastAPI parses the ISO string; ensure tz-aware UTC."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Routes
# NB: prefix /api
# ---------------------------------------------------------------------------

@router.get('/state',
            response_model=StateResponse,
            summary='Snapshot at one timestamp')
def get_state(t: datetime = Query(..., description='ISO-8601 UTC timestamp')) -> StateResponse:
    ts = _coerce_utc(t)
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"SELECT {META_COLS} FROM snapshot_meta WHERE interval_ts = %s",
                (ts,),
            )
            meta_row = cur.fetchone()
            if meta_row is None:
                raise HTTPException(status_code=404, detail=f'No snapshot at {ts.isoformat()}')

            cur.execute(
                "SELECT bus_id, fragility, lmp FROM bus_snapshots WHERE interval_ts = %s",
                (ts,),
            )
            bus_rows = cur.fetchall()

    meta = SnapshotMeta(**meta_row)
    buses = [BusState(**row) for row in bus_rows]
    return StateResponse(interval_ts=ts, meta=meta, buses=buses)


@router.get(
    '/state_range',
    response_model=StateRangeResponse,
    summary='Batch snapshots over a window (for prefetch)',
)
def get_state_range(
    start: datetime = Query(..., description='ISO-8601 UTC start (inclusive)'),
    end:   datetime = Query(..., description='ISO-8601 UTC end (exclusive)'),
) -> StateRangeResponse:

    #
    # Param Validation
    #
    s = _coerce_utc(start)
    e = _coerce_utc(end)
    if e <= s:
        raise HTTPException(status_code=400, detail='end must be after start')

    span_hours = (e - s).total_seconds() / 3600
    if span_hours > MAX_STATE_RANGE_HOURS:
        raise HTTPException(
            status_code=400,
            detail=f'Range exceeds {MAX_STATE_RANGE_HOURS}h cap; got {span_hours:.0f}h',
        )

    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT {META_COLS}
                FROM snapshot_meta
                WHERE interval_ts >= %s AND interval_ts < %s
                  AND status = 'ok'
                ORDER BY interval_ts
                """,
                (s, e),
            )
            meta_rows = cur.fetchall()

            if not meta_rows:
                return StateRangeResponse(start=s, end=e, count=0, entries=[])

            cur.execute(
                """
                SELECT interval_ts, bus_id, fragility, lmp
                FROM bus_snapshots
                WHERE interval_ts >= %s AND interval_ts < %s
                ORDER BY interval_ts, bus_id
                """,
                (s, e),
            )
            bus_rows = cur.fetchall()

    # Idea is to make two queries: meta [start, end], buses: [start, end]
    # then join them together, versus an N+1: meta then buses, meta then buses...
    #
    # Group bus rows by interval_ts:
    # grab interval_ts, then append to dict of lists
    # dict[interval_ts] -> [BusState]
    #
    # iterate meta_rows, and given interval_ts, pass the list of BusState at
    # that interval.
    bus_by_ts: dict[datetime, list[BusState]] = {}
    for row in bus_rows:
        ts = row.pop('interval_ts')
        bus_by_ts.setdefault(ts, []).append(BusState(**row))

    entries = [
        StateRangeEntry(
            interval_ts=row['interval_ts'],
            meta=SnapshotMeta(**row),
            buses=bus_by_ts.get(row['interval_ts'], []),
        )
        for row in meta_rows
    ]

    return StateRangeResponse(start=s, end=e, count=len(entries), entries=entries)
