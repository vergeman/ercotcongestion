"""DAM-close Conditions query service for the Map sidebar."""

from __future__ import annotations

import bisect
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from psycopg.rows import dict_row

from api.db import get_pool
from api.schemas.conditions import (
    ConditionsEntry,
    ConditionsRangeResponse,
    FuelOutage,
    RegionGen,
    ZoneLoad,
)
from api.services.time import CENTRAL, coerce_utc
from compute.mu_forecast.panel.availability import dam_close_expr

WEATHER_ZONES = (
    "coast", "east", "far_west", "north", "north_central", "south_central", "southern", "west",
)
WIND_REGIONS = ("panhandle", "coastal", "south", "west", "north")
SOLAR_REGIONS = (
    "centerwest", "northwest", "farwest", "fareast", "southeast", "centereast",
)
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


def _forecast_rows(cur, start: datetime, end: datetime, table: str, columns: str):
    cur.execute(
        f"""SELECT DISTINCT ON (interval_ts, dst_flag) interval_ts, {columns}
        FROM {table}
        WHERE interval_ts >= %s AND interval_ts <= %s
          AND posted_datetime <= {dam_close_expr("interval_ts")}
        ORDER BY interval_ts, dst_flag, posted_datetime DESC""",
        (start, end),
    )
    return cur.fetchall()


def _load_rows(cur, start: datetime, end: datetime):
    return _forecast_rows(
        cur, start, end, "load_forecast_zonal", ", ".join((*WEATHER_ZONES, "system_total"))
    )


def _load_by_ts(rows) -> dict[datetime, list[ZoneLoad]]:
    out = {}
    for row in rows:
        ts = coerce_utc(row["interval_ts"])
        values = [
            ZoneLoad(zone=zone, dam_close_mw=None if row[zone] is None else float(row[zone]))
            for zone in WEATHER_ZONES
        ]
        values.append(
            ZoneLoad(
                zone="system",
                dam_close_mw=(
                    None if row["system_total"] is None else float(row["system_total"])
                ),
            )
        )
        out[ts] = values
    return out


def _region_rows(cur, start, end, table, prefix, regions):
    columns = ", ".join([*(f"{prefix}_{region}" for region in regions), f"{prefix}_system_wide"])
    return _forecast_rows(cur, start, end, table, columns)


def _region_by_ts(rows, prefix, regions) -> dict[datetime, list[RegionGen]]:
    out = {}
    for row in rows:
        ts = coerce_utc(row["interval_ts"])
        values = [
            RegionGen(
                region=region,
                dam_close_mw=(
                    None if row[f"{prefix}_{region}"] is None else float(row[f"{prefix}_{region}"])
                ),
            )
            for region in regions
        ]
        values.append(
            RegionGen(
                region="system",
                dam_close_mw=(
                    None
                    if row[f"{prefix}_system_wide"] is None
                    else float(row[f"{prefix}_system_wide"])
                ),
            )
        )
        out[ts] = values
    return out


def _outage_rows(cur, lo_day: date, hi_day: date):
    cur.execute(
        """SELECT posted_date, fuel_type, effective_mw_reduction, planned_end_date
        FROM resource_outages WHERE posted_date >= %s AND posted_date <= %s""",
        (lo_day, hi_day),
    )
    return cur.fetchall()


def _outage_sums(rows: list[dict], ts: datetime) -> dict[str, float]:
    """Sum MW expected out at delivery, from a DAM-close-eligible snapshot."""
    sums: dict[str, float] = {}
    for row in rows:
        mw = row["effective_mw_reduction"]
        if mw is None or row["planned_end_date"] is None or row["planned_end_date"] < ts:
            continue
        bucket = FUEL_BUCKETS.get(row["fuel_type"] or "", "other")
        sums[bucket] = sums.get(bucket, 0.0) + float(mw)
    return sums


def _outage_fuels_at(
    snaps: dict[date, list[dict]], posted: list[date], ts: datetime
) -> list[FuelOutage]:
    vintage = _vintage_on_or_before(posted, _ct_date(ts) - timedelta(days=1))
    expected = _outage_sums(snaps[vintage], ts) if vintage else None
    fuels = [
        FuelOutage(
            fuel=fuel,
            dam_close_mw=None if expected is None else expected.get(fuel, 0.0),
        )
        for fuel in FUEL_ORDER
    ]
    fuels.append(
        FuelOutage(
            fuel="total", dam_close_mw=None if expected is None else sum(expected.values())
        )
    )
    return fuels


def conditions_range(start: datetime, end: datetime) -> ConditionsRangeResponse:
    """Return a normalized inclusive grid of DAM-close Conditions."""
    lo_day, hi_day = _ct_date(start) - timedelta(days=3), _ct_date(end) - timedelta(days=1)
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        load_rows = _load_rows(cur, start, end)
        wind_rows = _region_rows(cur, start, end, "wind_forecast_regional", "stwpf", WIND_REGIONS)
        solar_rows = _region_rows(cur, start, end, "solar_forecast_regional", "stppf", SOLAR_REGIONS)
        outages = _outage_rows(cur, lo_day, hi_day)

    if not any((load_rows, wind_rows, solar_rows, outages)):
        raise HTTPException(
            status_code=503,
            detail=f"no DAM-close load/wind/solar/outages rows in window {start} .. {end}.",
        )

    load = _load_by_ts(load_rows)
    wind = _region_by_ts(wind_rows, "stwpf", WIND_REGIONS)
    solar = _region_by_ts(solar_rows, "stppf", SOLAR_REGIONS)
    snapshots: dict[date, list[dict]] = {}
    for row in outages:
        snapshots.setdefault(row["posted_date"], []).append(row)
    posted = sorted(snapshots)
    entries = []
    ts = start
    while ts <= end:
        entries.append(
            ConditionsEntry(
                interval_ts=ts,
                load=load.get(ts, []),
                wind=wind.get(ts, []),
                solar=solar.get(ts, []),
                outages=_outage_fuels_at(snapshots, posted, ts) if snapshots else [],
            )
        )
        ts += timedelta(hours=1)
    return ConditionsRangeResponse(start=start, end=end, count=len(entries), entries=entries)
