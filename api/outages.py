"""GET /outages_range — per-hour outaged capacity by fuel type (NP1-346).

`resource_outages` (migration 27) is a DAILY D-vintage snapshot of active
unit-level outage events — its content changes once per posted_date, not once
per hour, unlike every other range endpoint here. This endpoint still emits
one entry per hour in [start, end] (the same shape the frontend's per-hour
cache already expects), replicating each day's aggregate across its 24 hours.

This is a genuinely different quantity from `/generation_range`: MW of
capacity currently OFFLINE, not MW being produced. Labeled `fuel`, never
`region`, to keep that distinction visible in the wire shape.

Two vintage rules, mirroring `compute.mu.outage_exposure`'s already-established
leak boundary (plan/0089) rather than inventing a new one:

  forecast_mw  the newest `posted_date` <= delivery-day D minus one day (NP1-346
               posts ~05:00 CT, before the 10:00 DAM close for D-1's delivery
               day D — see `compute.mu.outage_exposure._vintage`), summed over
               events whose `planned_end_date` is still >= the hour — "expected
               still out", the forward-looking, no-lookahead reading.
  actual_mw    the newest `posted_date` <= D itself (no D-1 restriction — a
               display reading of what happened, not a training feature),
               summed over events genuinely active at the hour:
               `actual_outage_start <= hour < actual_end_date` (or
               `actual_end_date` still null).

Fuel buckets mirror `compute.mu.outage_exposure.FUEL_BUCKETS` (gas/wind/solar,
else "other"), split finer for display — coal (Bituminous/Subbituminous Coal,
Lignite) and hydro (Water) pulled out of "other" — matching the prototype's
original 6-bucket table. Purely a display-layer split; the model feature's
4-bucket map is untouched. A `"total"` row sums across every bucket.
"""
from __future__ import annotations

import bisect
import logging
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from db import get_pool

from models import FuelOutage, OutagesEntry, OutagesRangeResponse

log = logging.getLogger(__name__)

router = APIRouter()

CENTRAL = ZoneInfo("America/Chicago")

FUEL_BUCKETS: dict[str, str] = {
    "Natural Gas": "gas",
    "Blast-Furnace Gas": "gas",
    "Wind": "wind",
    "Solar": "solar",
    "Bituminous Coal": "coal",
    "Subbituminous Coal": "coal",
    "Lignite": "coal",
    "Water": "hydro",
}
FUEL_ORDER = ("gas", "wind", "solar", "coal", "other", "hydro")


def _bucket_of(fuel_type: str | None) -> str:
    return FUEL_BUCKETS.get(fuel_type or "", "other")


def _coerce_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _ct_date(ts: datetime) -> date:
    return ts.astimezone(CENTRAL).date()


def _vintage_on_or_before(posted_sorted: list[date], target: date) -> date | None:
    i = bisect.bisect_right(posted_sorted, target) - 1
    return posted_sorted[i] if i >= 0 else None


def _fuel_sums(snapshot_rows: list[dict], ts: datetime, *, actual: bool) -> dict[str, float]:
    """Sum `effective_mw_reduction` by fuel bucket, for events counted at `ts`.

    `actual=True`: genuinely active at `ts` (start <= ts < end, or end is
    still null). `actual=False`: still expected out per `planned_end_date`.
    """
    out: dict[str, float] = {}
    for r in snapshot_rows:
        mw = r["effective_mw_reduction"]
        if mw is None:
            continue
        if actual:
            start = r["actual_outage_start"]
            end = r["actual_end_date"]
            if start is None or start > ts:
                continue
            if end is not None and end <= ts:
                continue
        else:
            planned_end = r["planned_end_date"]
            if planned_end is None or planned_end < ts:
                continue
        bucket = _bucket_of(r["fuel_type"])
        out[bucket] = out.get(bucket, 0.0) + float(mw)
    return out


@router.get(
    "/outages_range",
    response_model=OutagesRangeResponse,
    summary="Per-hour outaged capacity by fuel type (NP1-346)",
)
def get_outages_range(
    start: datetime = Query(..., description="ISO-8601 UTC start (inclusive)"),
    end: datetime = Query(..., description="ISO-8601 UTC end (inclusive)"),
) -> OutagesRangeResponse:
    start_u = _coerce_utc(start)
    end_u = _coerce_utc(end)

    # Headroom before `start` so a D-1 forecast vintage is resolvable even for
    # the window's first hour, and gaps in daily posting (weekends/holidays)
    # still find the nearest earlier snapshot.
    lo_day = _ct_date(start_u) - timedelta(days=3)
    hi_day = _ct_date(end_u)

    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT posted_date, fuel_type, effective_mw_reduction,
                       actual_outage_start, actual_end_date, planned_end_date
                FROM resource_outages
                WHERE posted_date >= %s AND posted_date <= %s
                """,
                (lo_day, hi_day),
            )
            rows = cur.fetchall()

    if not rows:
        raise HTTPException(
            status_code=503,
            detail=f"no resource_outages rows in window {lo_day} .. {hi_day}.",
        )

    snaps: dict[date, list[dict]] = {}
    for r in rows:
        snaps.setdefault(r["posted_date"], []).append(r)
    posted_sorted = sorted(snaps)

    entries = []
    ts = start_u
    while ts <= end_u:
        d = _ct_date(ts)
        actual_v = _vintage_on_or_before(posted_sorted, d)
        forecast_v = _vintage_on_or_before(posted_sorted, d - timedelta(days=1))

        actual_sums = _fuel_sums(snaps[actual_v], ts, actual=True) if actual_v else None
        forecast_sums = _fuel_sums(snaps[forecast_v], ts, actual=False) if forecast_v else None

        fuels = [
            FuelOutage(
                fuel=fuel,
                forecast_mw=None if forecast_sums is None else forecast_sums.get(fuel, 0.0),
                actual_mw=None if actual_sums is None else actual_sums.get(fuel, 0.0),
            )
            for fuel in FUEL_ORDER
        ]
        fuels.append(
            FuelOutage(
                fuel="total",
                forecast_mw=None if forecast_sums is None else sum(forecast_sums.values()),
                actual_mw=None if actual_sums is None else sum(actual_sums.values()),
            )
        )
        entries.append(OutagesEntry(interval_ts=ts, fuels=fuels))
        ts += timedelta(hours=1)

    return OutagesRangeResponse(
        start=start_u,
        end=end_u,
        count=len(entries),
        entries=entries,
    )
