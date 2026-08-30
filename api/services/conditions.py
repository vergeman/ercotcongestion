"""Conditions panel query service.

The response merges the map panel's Load, Wind, Solar, and Outages views.
Load and generation pair actuals with the latest forecast vintage posted no
later than each interval, preventing lookahead.  Outages use daily snapshots:
the forecast side is D-1 admissible while the actual side uses the newest
vintage available through the delivery day.

Every interval in the inclusive window is emitted.  Individual sources may be
missing for an hour; 503 is reserved for a window with no rows from any source.
"""
from __future__ import annotations

import bisect
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from psycopg.rows import dict_row

from api.db import get_pool
from api.schemas.conditions import ConditionsEntry, ConditionsRangeResponse, FuelOutage, RegionGen, ZoneLoad
from api.services.time import CENTRAL, coerce_utc

WEATHER_ZONES = ("coast", "east", "far_west", "north", "north_central", "south_central", "southern", "west")
WIND_REGIONS = ("panhandle", "coastal", "south", "west", "north")
SOLAR_REGIONS = ("centerwest", "northwest", "farwest", "fareast", "southeast", "centereast")
FUEL_BUCKETS = {
    "Natural Gas": "gas", "Blast-Furnace Gas": "gas", "Wind": "wind", "Solar": "solar",
    "Bituminous Coal": "coal", "Subbituminous Coal": "coal", "Lignite": "coal", "Water": "hydro",
}
FUEL_ORDER = ("gas", "wind", "solar", "coal", "other", "hydro")


def _ct_date(ts: datetime) -> date:
    return coerce_utc(ts).astimezone(CENTRAL).date()


def _vintage_on_or_before(posted: list[date], target: date) -> date | None:
    index = bisect.bisect_right(posted, target) - 1
    return posted[index] if index >= 0 else None


# --------------------------------------------------------------------------
# Load by weather zone
# --------------------------------------------------------------------------

def _load_rows(cur, start: datetime, end: datetime):
    # Load forecasts use the latest vintage knowable at the interval.
    zone_cols = ", ".join(WEATHER_ZONES)
    cur.execute(
        f"""SELECT DISTINCT ON (interval_ts) interval_ts, {zone_cols}, total
        FROM load_by_zone WHERE interval_ts >= %s AND interval_ts <= %s
        ORDER BY interval_ts, dst_flag ASC""", (start, end))
    actual = cur.fetchall()
    cur.execute(
        f"""SELECT DISTINCT ON (interval_ts) interval_ts, {zone_cols}, system_total
        FROM load_forecast_zonal
        WHERE interval_ts >= %s AND interval_ts <= %s AND posted_datetime <= interval_ts
        ORDER BY interval_ts, dst_flag ASC, posted_datetime DESC""", (start, end))
    return actual, cur.fetchall()


def _load_by_ts(actual_rows, forecast_rows) -> dict[datetime, list[ZoneLoad]]:
    actual = {coerce_utc(row["interval_ts"]): row for row in actual_rows}
    forecast = {coerce_utc(row["interval_ts"]): row for row in forecast_rows}
    out = {}
    for ts in set(actual) | set(forecast):
        a, f = actual.get(ts), forecast.get(ts)
        rows = [
            ZoneLoad(zone=zone, actual_mw=None if a is None or a[zone] is None else float(a[zone]),
                     forecast_mw=None if f is None or f[zone] is None else float(f[zone]))
            for zone in WEATHER_ZONES
        ]
        rows.append(ZoneLoad(
            zone="system", actual_mw=None if a is None or a["total"] is None else float(a["total"]),
            forecast_mw=None if f is None or f["system_total"] is None else float(f["system_total"]),
        ))
        out[ts] = rows
    return out


# --------------------------------------------------------------------------
# Wind / solar by region
# --------------------------------------------------------------------------

def _region_rows(cur, start, end, actual_table, forecast_table, regions):
    """Read actual and no-lookahead forecast rows for wind or solar."""
    region_cols = ", ".join(f"gen_{region}" for region in regions)
    cur.execute(
        f"""SELECT DISTINCT ON (interval_ts) interval_ts, {region_cols}, gen_system_wide
        FROM {actual_table} WHERE interval_ts >= %s AND interval_ts <= %s
        ORDER BY interval_ts, dst_flag ASC""", (start, end))
    actual = cur.fetchall()
    prefix = "stwpf" if actual_table == "wind_hourly_regional" else "stppf"
    forecast_cols = ", ".join(f"{prefix}_{region}" for region in regions)
    cur.execute(
        f"""SELECT DISTINCT ON (interval_ts) interval_ts, {forecast_cols}, {prefix}_system_wide
        FROM {forecast_table}
        WHERE interval_ts >= %s AND interval_ts <= %s AND posted_datetime <= interval_ts
        ORDER BY interval_ts, dst_flag ASC, posted_datetime DESC""", (start, end))
    return actual, cur.fetchall(), prefix


def _region_by_ts(actual_rows, forecast_rows, prefix, regions) -> dict[datetime, list[RegionGen]]:
    actual = {coerce_utc(row["interval_ts"]): row for row in actual_rows}
    forecast = {coerce_utc(row["interval_ts"]): row for row in forecast_rows}
    out = {}
    for ts in set(actual) | set(forecast):
        a, f = actual.get(ts), forecast.get(ts)
        rows = [
            RegionGen(region=region, actual_mw=None if a is None or a[f"gen_{region}"] is None else float(a[f"gen_{region}"]),
                      forecast_mw=None if f is None or f[f"{prefix}_{region}"] is None else float(f[f"{prefix}_{region}"]))
            for region in regions
        ]
        rows.append(RegionGen(
            region="system", actual_mw=None if a is None or a["gen_system_wide"] is None else float(a["gen_system_wide"]),
            forecast_mw=None if f is None or f[f"{prefix}_system_wide"] is None else float(f[f"{prefix}_system_wide"]),
        ))
        out[ts] = rows
    return out


# --------------------------------------------------------------------------
# Outages by fuel
# --------------------------------------------------------------------------

def _outage_rows(cur, lo_day: date, hi_day: date):
    cur.execute(
        """SELECT posted_date, fuel_type, effective_mw_reduction, actual_outage_start,
        actual_end_date, planned_end_date FROM resource_outages
        WHERE posted_date >= %s AND posted_date <= %s""", (lo_day, hi_day))
    return cur.fetchall()


def _outage_sums(rows: list[dict], ts: datetime, *, actual: bool) -> dict[str, float]:
    """Sum outage reductions by fuel bucket for events counted at ``ts``.

    Actuals are genuinely active (start <= ts < end, or no end); forecasts are
    still expected out according to ``planned_end_date``.
    """
    sums: dict[str, float] = {}
    for row in rows:
        mw = row["effective_mw_reduction"]
        if mw is None:
            continue
        if actual:
            if row["actual_outage_start"] is None or row["actual_outage_start"] > ts:
                continue
            if row["actual_end_date"] is not None and row["actual_end_date"] <= ts:
                continue
        elif row["planned_end_date"] is None or row["planned_end_date"] < ts:
            continue
        bucket = FUEL_BUCKETS.get(row["fuel_type"] or "", "other")
        sums[bucket] = sums.get(bucket, 0.0) + float(mw)
    return sums


def _outage_fuels_at(snaps: dict[date, list[dict]], posted: list[date], ts: datetime) -> list[FuelOutage]:
    day = _ct_date(ts)
    actual_vintage = _vintage_on_or_before(posted, day)
    forecast_vintage = _vintage_on_or_before(posted, day - timedelta(days=1))
    actual = _outage_sums(snaps[actual_vintage], ts, actual=True) if actual_vintage else None
    forecast = _outage_sums(snaps[forecast_vintage], ts, actual=False) if forecast_vintage else None
    fuels = [
        FuelOutage(fuel=fuel, forecast_mw=None if forecast is None else forecast.get(fuel, 0.0),
                   actual_mw=None if actual is None else actual.get(fuel, 0.0))
        for fuel in FUEL_ORDER
    ]
    fuels.append(FuelOutage(
        fuel="total", forecast_mw=None if forecast is None else sum(forecast.values()),
        actual_mw=None if actual is None else sum(actual.values()),
    ))
    return fuels


def conditions_range(start: datetime, end: datetime) -> ConditionsRangeResponse:
    """Return all Conditions sources for a normalized inclusive interval."""
    # Headroom resolves the D-1 outage forecast vintage through posting gaps.
    lo_day, hi_day = _ct_date(start) - timedelta(days=3), _ct_date(end)
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        load_actual, load_forecast = _load_rows(cur, start, end)
        wind_actual, wind_forecast, wind_prefix = _region_rows(
            cur, start, end, "wind_hourly_regional", "wind_forecast_regional", WIND_REGIONS)
        solar_actual, solar_forecast, solar_prefix = _region_rows(
            cur, start, end, "solar_hourly_regional", "solar_forecast_regional", SOLAR_REGIONS)
        outages = _outage_rows(cur, lo_day, hi_day)

    if not any((load_actual, load_forecast, wind_actual, wind_forecast, solar_actual, solar_forecast, outages)):
        raise HTTPException(status_code=503, detail=f"no load/wind/solar/outages rows in window {start} .. {end}.")

    load = _load_by_ts(load_actual, load_forecast)
    wind = _region_by_ts(wind_actual, wind_forecast, wind_prefix, WIND_REGIONS)
    solar = _region_by_ts(solar_actual, solar_forecast, solar_prefix, SOLAR_REGIONS)
    # Preserve daily snapshot vintages for the per-hour outage policy.
    snapshots: dict[date, list[dict]] = {}
    for row in outages:
        snapshots.setdefault(row["posted_date"], []).append(row)
    posted = sorted(snapshots)
    entries = []
    ts = start
    while ts <= end:
        entries.append(ConditionsEntry(
            interval_ts=ts, load=load.get(ts, []), wind=wind.get(ts, []), solar=solar.get(ts, []),
            outages=_outage_fuels_at(snapshots, posted, ts) if snapshots else [],
        ))
        ts += timedelta(hours=1)
    return ConditionsRangeResponse(start=start, end=end, count=len(entries), entries=entries)
