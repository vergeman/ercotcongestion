"""GET /load_zone_range — per-hour load by ERCOT weather zone for a window.

The regional counterpart to ``/ercot_spp_range``'s ``total_load_mw``: that
endpoint reads only the ``total`` column of ``load_by_zone``, never the 8
per-zone columns. This endpoint exposes both the actual per-zone load
(NP6-345-CD, ``load_by_zone``) and the forecast per-zone load (NP3-561-CD,
``load_forecast_zonal``) side by side.

``load_forecast_zonal`` is vintaged on ``(posted_datetime, interval_ts,
dst_flag)`` — ~24 publishes/day, each covering 168 forecast hours. We read the
latest vintage posted no later than the hour it describes
(``posted_datetime <= interval_ts``), the same no-lookahead boundary
``compute.analysis.hero_window`` applies when building model features, so the
forecast column here is never a hindsight value.

Both sides soft-fail independently — a delivery day with only a forecast
posted (pre-market) or only actuals (forecast window elapsed) is normal, not
an error. 503 only when the window has no rows on either side at all.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from db import get_pool

from models import LoadZoneEntry, LoadZoneRangeResponse, ZoneLoad

log = logging.getLogger(__name__)

router = APIRouter()

# The 8 NP3-561/NP6-345 weather zones (compute.ercot.zones.WEATHER_ZONES),
# plus the system-wide total row.
WEATHER_ZONES = (
    "coast", "east", "far_west", "north",
    "north_central", "south_central", "southern", "west",
)


def _coerce_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


@router.get(
    "/load_zone_range",
    response_model=LoadZoneRangeResponse,
    summary="Per-hour actual + forecast load by ERCOT weather zone",
)
def get_load_zone_range(
    start: datetime = Query(..., description="ISO-8601 UTC start (inclusive)"),
    end: datetime = Query(..., description="ISO-8601 UTC end (inclusive)"),
) -> LoadZoneRangeResponse:
    start_u = _coerce_utc(start)
    end_u = _coerce_utc(end)

    zone_cols = ", ".join(WEATHER_ZONES)

    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT DISTINCT ON (interval_ts)
                       interval_ts, {zone_cols}, total
                FROM load_by_zone
                WHERE interval_ts >= %s AND interval_ts <= %s
                ORDER BY interval_ts, dst_flag ASC
                """,
                (start_u, end_u),
            )
            actual_rows = cur.fetchall()

            cur.execute(
                f"""
                SELECT DISTINCT ON (interval_ts)
                       interval_ts, {zone_cols}, system_total
                FROM load_forecast_zonal
                WHERE interval_ts >= %s AND interval_ts <= %s
                  AND posted_datetime <= interval_ts
                ORDER BY interval_ts, dst_flag ASC, posted_datetime DESC
                """,
                (start_u, end_u),
            )
            forecast_rows = cur.fetchall()

    if not actual_rows and not forecast_rows:
        raise HTTPException(
            status_code=503,
            detail=(
                f"no load_by_zone or load_forecast_zonal rows in window "
                f"{start_u} .. {end_u}."
            ),
        )

    actual_by_ts = {_coerce_utc(r["interval_ts"]): r for r in actual_rows}
    forecast_by_ts = {_coerce_utc(r["interval_ts"]): r for r in forecast_rows}

    entries = []
    for ts in sorted(set(actual_by_ts) | set(forecast_by_ts)):
        a = actual_by_ts.get(ts)
        f = forecast_by_ts.get(ts)
        zones = [
            ZoneLoad(
                zone=zone,
                actual_mw=None if a is None or a[zone] is None else float(a[zone]),
                forecast_mw=None if f is None or f[zone] is None else float(f[zone]),
            )
            for zone in WEATHER_ZONES
        ]
        zones.append(
            ZoneLoad(
                zone="system",
                actual_mw=None if a is None or a["total"] is None else float(a["total"]),
                forecast_mw=None if f is None or f["system_total"] is None else float(f["system_total"]),
            )
        )
        entries.append(LoadZoneEntry(interval_ts=ts, zones=zones))

    return LoadZoneRangeResponse(
        start=start_u,
        end=end_u,
        count=len(entries),
        entries=entries,
    )
