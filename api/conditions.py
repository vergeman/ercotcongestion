"""GET /conditions_range — per-hour Load / Wind / Solar / Outages, merged.

One response for everything the map's "Conditions" panel shows (plan/0141),
replacing three separate endpoints (`load_zone_range`, `generation_range`,
`outages_range`) once the frontend settled on presenting them as one section:
each Conditions row needs both `forecast_mw` and `actual_mw` simultaneously
(the map's Forecast/Market/Compare/Error toggle picks one client-side), so
splitting this across separate actual/forecast requests — the shape
`/ercot_range` + `/forecast_range` use for per-SP congestion — would only
reintroduce the client-side merge this was designed to avoid. It stays its own
endpoint rather than folding into those two: they are per-settlement-point
(~1,100 SPs/hour, a heavy hot-path payload), this is per-region/per-fuel
aggregates — different granularity, no reason to share a response.

  load    actual (NP6-345-CD, `load_by_zone`) alongside forecast (NP3-561-CD,
          `load_forecast_zonal`, read at the latest vintage posted no later
          than `interval_ts` — no lookahead). `zone` is one of the 8 weather
          zones in `compute.ercot.zones.WEATHER_ZONES`, plus `"system"`.
  wind/solar
          actual (NP4-732-CD / NP4-737-CD, `wind_hourly_regional` /
          `solar_hourly_regional`) alongside forecast (`wind_forecast_regional`
          / `solar_forecast_regional`, STWPF/STPPF, same no-lookahead vintage
          rule) — NOT the migration-06 actual tables' own forecast-looking
          columns, which dedup to the most recent posting (~49h after the
          hour) and are not knowable ahead of time. `region` is one of the
          5 wind / 6 solar regions, plus `"system"`.
  outages a DIFFERENT quantity from wind/solar — MW currently OFFLINE
          (NP1-346 unplanned resource outages), not MW produced — and a
          different cadence underneath: `resource_outages` (migration 27) is
          a daily D-vintage snapshot, not an hourly series, so a day's values
          repeat across its 24 hourly entries. `fuel` is one of gas/wind/
          solar/coal/other/hydro, plus `"total"`. `forecast_mw` is the
          D-1-admissible vintage (mirrors `compute.mu_forecast.covariates.outages.exposure`'s
          leak boundary) summed over still-expected-out events; `actual_mw`
          is the newest vintage through the day itself, summed over
          genuinely-active-at-that-hour events.

Every hour in `[start, end]` gets an entry — outages needs a dense hourly
grid regardless (its vintage resolution is inherently per-hour), so load/wind/
solar ride the same grid rather than only emitting hours with a real row;
a source with nothing for an hour just contributes an empty list there, which
the client already renders as "—" per row (same outcome, simpler server code).

503 only when none of the four sources have a single row anywhere in the
window — each source degrades independently otherwise (a pre-market hour has
forecast with no actual, an elapsed forecast window has actual with no
forecast; that is normal, not an error).
"""
from __future__ import annotations

import bisect
import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from db import get_pool
from services.time import CENTRAL, coerce_utc

from schemas.conditions import (
    ConditionsEntry,
    ConditionsRangeResponse,
    FuelOutage,
    RegionGen,
    ZoneLoad,
)

log = logging.getLogger(__name__)

router = APIRouter()

WEATHER_ZONES = (
    "coast", "east", "far_west", "north",
    "north_central", "south_central", "southern", "west",
)
WIND_REGIONS = ("panhandle", "coastal", "south", "west", "north")
SOLAR_REGIONS = ("centerwest", "northwest", "farwest", "fareast", "southeast", "centereast")

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


def _ct_date(ts: datetime) -> date:
    return coerce_utc(ts).astimezone(CENTRAL).date()


def _vintage_on_or_before(posted_sorted: list[date], target: date) -> date | None:
    i = bisect.bisect_right(posted_sorted, target) - 1
    return posted_sorted[i] if i >= 0 else None


# --------------------------------------------------------------------------
# Load by weather zone
# --------------------------------------------------------------------------

def _load_rows(cur, start_u: datetime, end_u: datetime):
    zone_cols = ", ".join(WEATHER_ZONES)
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
    return actual_rows, forecast_rows


def _load_by_ts(actual_rows, forecast_rows) -> dict[datetime, list[ZoneLoad]]:
    actual_by_ts = {coerce_utc(r["interval_ts"]): r for r in actual_rows}
    forecast_by_ts = {coerce_utc(r["interval_ts"]): r for r in forecast_rows}
    out: dict[datetime, list[ZoneLoad]] = {}
    for ts in set(actual_by_ts) | set(forecast_by_ts):
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
        out[ts] = zones
    return out


# --------------------------------------------------------------------------
# Wind / solar by region
# --------------------------------------------------------------------------

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


def _region_by_ts(actual_rows, forecast_rows, fc_col, regions) -> dict[datetime, list[RegionGen]]:
    actual_by_ts = {coerce_utc(r["interval_ts"]): r for r in actual_rows}
    forecast_by_ts = {coerce_utc(r["interval_ts"]): r for r in forecast_rows}
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


# --------------------------------------------------------------------------
# Outages by fuel
# --------------------------------------------------------------------------

def _outage_rows(cur, lo_day: date, hi_day: date):
    cur.execute(
        """
        SELECT posted_date, fuel_type, effective_mw_reduction,
               actual_outage_start, actual_end_date, planned_end_date
        FROM resource_outages
        WHERE posted_date >= %s AND posted_date <= %s
        """,
        (lo_day, hi_day),
    )
    return cur.fetchall()


def _outage_fuel_sums(snapshot_rows: list[dict], ts: datetime, *, actual: bool) -> dict[str, float]:
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


def _outage_fuels_at(
    snaps: dict[date, list[dict]], posted_sorted: list[date], ts: datetime
) -> list[FuelOutage]:
    d = _ct_date(ts)
    actual_v = _vintage_on_or_before(posted_sorted, d)
    forecast_v = _vintage_on_or_before(posted_sorted, d - timedelta(days=1))

    actual_sums = _outage_fuel_sums(snaps[actual_v], ts, actual=True) if actual_v else None
    forecast_sums = _outage_fuel_sums(snaps[forecast_v], ts, actual=False) if forecast_v else None

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
    return fuels


@router.get(
    "/conditions_range",
    response_model=ConditionsRangeResponse,
    summary="Per-hour Load / Wind / Solar / Outages, merged",
)
def get_conditions_range(
    start: datetime = Query(..., description="ISO-8601 UTC start (inclusive)"),
    end: datetime = Query(..., description="ISO-8601 UTC end (inclusive)"),
) -> ConditionsRangeResponse:
    start_u = coerce_utc(start)
    end_u = coerce_utc(end)

    # Headroom before `start` so outages' D-1 forecast vintage is resolvable
    # even for the window's first hour, and gaps in daily posting (weekends/
    # holidays) still find the nearest earlier snapshot.
    lo_day = _ct_date(start_u) - timedelta(days=3)
    hi_day = _ct_date(end_u)

    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            load_actual, load_forecast = _load_rows(cur, start_u, end_u)
            wind_actual, wind_forecast, wind_fc_col = _region_rows(
                cur, start_u, end_u,
                "wind_hourly_regional", "wind_forecast_regional", WIND_REGIONS,
            )
            solar_actual, solar_forecast, solar_fc_col = _region_rows(
                cur, start_u, end_u,
                "solar_hourly_regional", "solar_forecast_regional", SOLAR_REGIONS,
            )
            outage_rows = _outage_rows(cur, lo_day, hi_day)

    if not any((
        load_actual, load_forecast, wind_actual, wind_forecast,
        solar_actual, solar_forecast, outage_rows,
    )):
        raise HTTPException(
            status_code=503,
            detail=(
                f"no load/wind/solar/outages rows in window {start_u} .. {end_u}."
            ),
        )

    load_by_ts = _load_by_ts(load_actual, load_forecast)
    wind_by_ts = _region_by_ts(wind_actual, wind_forecast, wind_fc_col, WIND_REGIONS)
    solar_by_ts = _region_by_ts(solar_actual, solar_forecast, solar_fc_col, SOLAR_REGIONS)

    outage_snaps: dict[date, list[dict]] = {}
    for r in outage_rows:
        outage_snaps.setdefault(r["posted_date"], []).append(r)
    outage_posted_sorted = sorted(outage_snaps)

    entries = []
    ts = start_u
    while ts <= end_u:
        entries.append(
            ConditionsEntry(
                interval_ts=ts,
                load=load_by_ts.get(ts, []),
                wind=wind_by_ts.get(ts, []),
                solar=solar_by_ts.get(ts, []),
                outages=(
                    _outage_fuels_at(outage_snaps, outage_posted_sorted, ts)
                    if outage_snaps else []
                ),
            )
        )
        ts += timedelta(hours=1)

    return ConditionsRangeResponse(
        start=start_u,
        end=end_u,
        count=len(entries),
        entries=entries,
    )
