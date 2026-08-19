"""GET /generation_range — per-hour wind + solar generation by ERCOT region.

Two independent region groups in one response: wind (NP4-732-CD, 5 regions —
Panhandle, Coastal, South, West, North) and solar (NP4-737-CD, 6 regions —
CenterWest, NorthWest, FarWest, FarEast, SouthEast, CenterEast), each with a
"system" row for the system-wide total.

Actuals come from the migration-06 tables (``wind_hourly_regional`` /
``solar_hourly_regional``), which dedup to the most recent posting per hour —
correct for "what happened". Forecasts come from the migration-26 vintaged
tables (``wind_forecast_regional`` / ``solar_forecast_regional``) instead of
those same migration-06 tables' own STWPF/STPPF columns: that migration's own
comment documents the actual-side tables' forecast columns as unsafe (median
publish lag +48.9h, 0% knowable at DAM close). We read the latest forecast
vintage posted no later than the hour it describes
(``posted_datetime <= interval_ts``), matching ``/load_zone_range`` and
``compute.analysis.hero_window``'s no-lookahead convention.

Both sides, and both region groups, soft-fail independently — a delivery day
with only a forecast posted (pre-market) or only actuals is normal. 503 only
when the window has no wind or solar rows at all, on either side.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from db import get_pool

from models import GenerationEntry, GenerationRangeResponse, RegionGen

log = logging.getLogger(__name__)

router = APIRouter()

WIND_REGIONS = ("panhandle", "coastal", "south", "west", "north")
SOLAR_REGIONS = ("centerwest", "northwest", "farwest", "fareast", "southeast", "centereast")


def _coerce_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _region_rows(cur, start_u, end_u, actual_table, forecast_table, regions):
    """Actual + forecast rows for one region group (wind or solar).

    Returns (actual_rows, forecast_rows, forecast_column_prefix).
    """
    region_cols = ", ".join(f"gen_{r}" for r in regions)
    cur.execute(
        f"""
        SELECT DISTINCT ON (interval_ts)
               interval_ts, {region_cols}, gen_system_wide
        FROM {actual_table}
        WHERE interval_ts >= %s AND interval_ts <= %s
        ORDER BY interval_ts, dst_flag ASC
        """,
        (start_u, end_u),
    )
    actual_rows = cur.fetchall()

    fc_col = "stwpf" if actual_table == "wind_hourly_regional" else "stppf"
    fc_cols = ", ".join(f"{fc_col}_{r}" for r in regions)
    cur.execute(
        f"""
        SELECT DISTINCT ON (interval_ts)
               interval_ts, {fc_cols}, {fc_col}_system_wide
        FROM {forecast_table}
        WHERE interval_ts >= %s AND interval_ts <= %s
          AND posted_datetime <= interval_ts
        ORDER BY interval_ts, dst_flag ASC, posted_datetime DESC
        """,
        (start_u, end_u),
    )
    forecast_rows = cur.fetchall()
    return actual_rows, forecast_rows, fc_col


def _to_entries(actual_rows, forecast_rows, fc_col, regions) -> dict[datetime, list[RegionGen]]:
    actual_by_ts = {_coerce_utc(r["interval_ts"]): r for r in actual_rows}
    forecast_by_ts = {_coerce_utc(r["interval_ts"]): r for r in forecast_rows}
    out: dict[datetime, list[RegionGen]] = {}
    for ts in set(actual_by_ts) | set(forecast_by_ts):
        a = actual_by_ts.get(ts)
        f = forecast_by_ts.get(ts)
        rows = [
            RegionGen(
                region=region,
                actual_mw=None if a is None or a[f"gen_{region}"] is None else float(a[f"gen_{region}"]),
                forecast_mw=None if f is None or f[f"{fc_col}_{region}"] is None else float(f[f"{fc_col}_{region}"]),
            )
            for region in regions
        ]
        rows.append(
            RegionGen(
                region="system",
                actual_mw=None if a is None or a["gen_system_wide"] is None else float(a["gen_system_wide"]),
                forecast_mw=None if f is None or f[f"{fc_col}_system_wide"] is None else float(f[f"{fc_col}_system_wide"]),
            )
        )
        out[ts] = rows
    return out


@router.get(
    "/generation_range",
    response_model=GenerationRangeResponse,
    summary="Per-hour actual + forecast wind and solar generation by ERCOT region",
)
def get_generation_range(
    start: datetime = Query(..., description="ISO-8601 UTC start (inclusive)"),
    end: datetime = Query(..., description="ISO-8601 UTC end (inclusive)"),
) -> GenerationRangeResponse:
    start_u = _coerce_utc(start)
    end_u = _coerce_utc(end)

    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            wind_actual, wind_forecast, wind_fc_col = _region_rows(
                cur, start_u, end_u,
                "wind_hourly_regional", "wind_forecast_regional", WIND_REGIONS,
            )
            solar_actual, solar_forecast, solar_fc_col = _region_rows(
                cur, start_u, end_u,
                "solar_hourly_regional", "solar_forecast_regional", SOLAR_REGIONS,
            )

    if not any((wind_actual, wind_forecast, solar_actual, solar_forecast)):
        raise HTTPException(
            status_code=503,
            detail=(
                f"no wind or solar regional rows in window {start_u} .. {end_u}."
            ),
        )

    wind_by_ts = _to_entries(wind_actual, wind_forecast, wind_fc_col, WIND_REGIONS)
    solar_by_ts = _to_entries(solar_actual, solar_forecast, solar_fc_col, SOLAR_REGIONS)

    entries = [
        GenerationEntry(
            interval_ts=ts,
            wind=wind_by_ts.get(ts, []),
            solar=solar_by_ts.get(ts, []),
        )
        for ts in sorted(set(wind_by_ts) | set(solar_by_ts))
    ]

    return GenerationRangeResponse(
        start=start_u,
        end=end_u,
        count=len(entries),
        entries=entries,
    )
