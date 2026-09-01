"""Small, as-of trailing-window readers for the v6 hero.

These readers intentionally aggregate in Postgres rather than borrowing the SF
panel loaders, which pivot thousands of hourly columns before reducing them.
All end bounds are exclusive delivery-day boundaries in America/Chicago: a
re-run for a past day therefore cannot see a later backfill.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from compute.time import ERCOT_TZ as ERCOT_TZ_NAME, delivery_bounds

ERCOT_TZ = ZoneInfo(ERCOT_TZ_NAME)
HIGH_CONGESTION_CT_HOURS = (15, 16, 17, 18)  # Empirical slice; not a market on-peak definition.


def _rows(cur, columns: tuple[str, ...]) -> list[dict[str, Any]]:
    """Normalize psycopg tuple rows and dict-row test cursors."""
    result = []
    for row in cur.fetchall():
        result.append(dict(row) if isinstance(row, dict) else dict(zip(columns, row)))
    return result


def load_constraint_days(conn, delivery_date: date, *, days: int = 30,
                         constraint_keys: list[str] | None = None,
                         ct_hours: tuple[int, ...] | None = None) -> list[dict[str, Any]]:
    """Return one daily ``Σμ`` row per constraint from the trailing window.

    ``end`` is midnight CT immediately after ``delivery_date``.  Its strict
    ``interval_ts < end`` predicate is the reproducibility boundary; do not turn
    it into a query relative to ``now()``.
    """
    start, end = delivery_bounds(delivery_date)
    start -= timedelta(days=days)
    key_clause = ""
    hour_clause = ""
    params: list[Any] = [start, end]
    if constraint_keys is not None:
        key_clause = " AND (btrim(constraint_name) || '|' || btrim(contingency_name)) = ANY(%s)"
        params.append(constraint_keys)
    if ct_hours is not None:
        hour_clause = " AND EXTRACT(hour FROM interval_ts AT TIME ZONE 'America/Chicago') = ANY(%s)"
        params.append(list(ct_hours))
    sql = f"""
        SELECT (interval_ts AT TIME ZONE 'America/Chicago')::date AS delivery_date,
               btrim(constraint_name) || '|' || btrim(contingency_name) AS constraint_key,
               SUM(shadow_price) AS value,
               COUNT(*) FILTER (WHERE shadow_price <> 0) AS hours_bound
        FROM ercot_dam_shadow_prices
        WHERE interval_ts >= %s AND interval_ts < %s
          AND dst_flag = FALSE AND shadow_price IS NOT NULL{key_clause}{hour_clause}
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        return _rows(cur, ("delivery_date", "constraint_key", "value", "hours_bound"))


def load_forecast_constraint_days(conn, run_id: str, delivery_date: date, horizon: int,
                                  *, days: int = 30,
                                  constraint_keys: list[str] | None = None) -> list[dict[str, Any]]:
    """Return persisted daily forecast ``Σμ`` rows through ``delivery_date``.

    The historical vocabulary is explicitly restricted to the served artifact's
    keys.  This keeps the forecast comparison like-for-like even if a past fit
    carried a different constraint set.
    """
    params: list[Any] = [run_id, horizon, delivery_date - timedelta(days=days), delivery_date]
    key_clause = ""
    if constraint_keys is not None:
        key_clause = " AND constraint_key = ANY(%s)"
        params.append(constraint_keys)
    sql = f"""
        SELECT delivery_date, constraint_key, forecast_mu AS value, binding_hours
        FROM forecast_constraint_daily
        WHERE run_id = %s AND horizon = %s
          AND delivery_date >= %s AND delivery_date <= %s{key_clause}
        ORDER BY delivery_date, constraint_key
    """
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        return _rows(cur, ("delivery_date", "constraint_key", "value", "binding_hours"))


def summarize_constraint_days(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Organize aggregated constraint rows for a classifier or API response."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["constraint_key"])].append(row)
    return {
        key: {
            "series": [{"delivery_date": str(r["delivery_date"]), "value": float(r["value"])}
                       for r in values],
            "days_bound": sum(float(r["value"]) != 0 for r in values),
            "med": float(median(float(r["value"]) for r in values)),
            "prior_last": float(values[-2]["value"]) if len(values) > 1 else None,
        }
        for key, values in grouped.items()
    }


def daily_total(rows: list[dict[str, Any]], delivery_date: date, *, days: int) -> list[float]:
    """Sum a constraint-row result into a zero-filled daily total series."""
    totals: dict[date, float] = defaultdict(float)
    for row in rows:
        totals[row["delivery_date"]] += float(row["value"])
    first = delivery_date - timedelta(days=days)
    return [totals[first + timedelta(days=offset)] for offset in range(days + 1)]


def load_constraint_geo(conn) -> list[dict[str, Any]]:
    """Read one coherent, newest persisted geography window.

    Selecting the latest row per key can splice several map runs into one hero and
    makes ``geo_as_of`` ambiguous.  The hero instead uses the complete newest
    window, so every zone share carries the same provenance stamp.
    """
    sql = """
        SELECT constraint_key, zone_shares, window_start::date AS geo_as_of
        FROM constraint_geo
        WHERE window_start = (SELECT max(window_start) FROM constraint_geo)
          AND zone_shares IS NOT NULL
        ORDER BY constraint_key
    """
    with conn.cursor() as cur:
        cur.execute(sql, ())
        return _rows(cur, ("constraint_key", "zone_shares", "geo_as_of"))


def load_node_days(conn, delivery_date: date, *, days: int = 30) -> list[dict[str, Any]]:
    """Return trailing daily mean SPP-minus-λ congestion per settlement point."""
    start, end = delivery_bounds(delivery_date)
    start -= timedelta(days=days)
    sql = """
        SELECT (s.interval_ts AT TIME ZONE 'America/Chicago')::date AS delivery_date,
               s.settlement_point,
               AVG(s.dam_spp - l.system_lambda) AS value
        FROM ercot_dam_spp s
        JOIN dam_system_lambda l
          ON l.interval_ts = s.interval_ts AND l.dst_flag = s.dst_flag
        WHERE s.interval_ts >= %s AND s.interval_ts < %s
          AND s.dst_flag = FALSE
        GROUP BY 1, 2
        ORDER BY 1, 2
    """
    with conn.cursor() as cur:
        cur.execute(sql, (start, end))
        return _rows(cur, ("delivery_date", "settlement_point", "value"))


def summarize_node_days(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Organize node daily-mean congestion series and today's absolute rank."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["settlement_point"])].append(row)
    result = {}
    for point, values in grouped.items():
        current = float(values[-1]["value"])
        rank, n = 1 + sum(abs(float(r["value"])) >= abs(current) for r in values[:-1]), len(values)
        result[point] = {
            "series": [{"delivery_date": str(r["delivery_date"]), "value": float(r["value"])}
                       for r in values],
            "rank": rank,
            "n": n,
        }
    return result


def load_load_condition(conn, delivery_date: date, *, days: int = 365) -> list[dict[str, Any]]:
    """Return each day's DAM-close-vintaged peak total and net-load forecasts.

    The daily peaks are intelligible system-load conditions and the query keeps
    only forecasts published by that delivery day's 10:00 CT DAM close. Net load
    is total load minus ERCOT's system-wide wind and solar point forecasts.
    """
    start, end = delivery_bounds(delivery_date)
    start -= timedelta(days=days)
    sql = """
        WITH load_vintaged AS (
            SELECT DISTINCT ON (interval_ts, dst_flag)
                   interval_ts, dst_flag, system_total
            FROM load_forecast_zonal
            WHERE interval_ts >= %s AND interval_ts < %s
              AND posted_datetime <= (
                (date_trunc('day', interval_ts AT TIME ZONE 'America/Chicago')
                  - interval '1 day' + interval '10 hours')
                AT TIME ZONE 'America/Chicago'
              )
            ORDER BY interval_ts, dst_flag, posted_datetime DESC
        ), wind_vintaged AS (
            SELECT DISTINCT ON (interval_ts, dst_flag)
                   interval_ts, dst_flag, stwpf_system_wide
            FROM wind_forecast_regional
            WHERE interval_ts >= %s AND interval_ts < %s
              AND posted_datetime <= (
                (date_trunc('day', interval_ts AT TIME ZONE 'America/Chicago')
                  - interval '1 day' + interval '10 hours')
                AT TIME ZONE 'America/Chicago'
              )
            ORDER BY interval_ts, dst_flag, posted_datetime DESC
        ), solar_vintaged AS (
            SELECT DISTINCT ON (interval_ts, dst_flag)
                   interval_ts, dst_flag, stppf_system_wide
            FROM solar_forecast_regional
            WHERE interval_ts >= %s AND interval_ts < %s
              AND posted_datetime <= (
                (date_trunc('day', interval_ts AT TIME ZONE 'America/Chicago')
                  - interval '1 day' + interval '10 hours')
                AT TIME ZONE 'America/Chicago'
              )
            ORDER BY interval_ts, dst_flag, posted_datetime DESC
        ), actual_daily AS (
            SELECT (l.interval_ts AT TIME ZONE 'America/Chicago')::date AS delivery_date,
                   MAX(l.total) AS actual_value,
                   MAX(l.total - w.gen_system_wide - s.gen_system_wide) AS actual_net_load
            FROM load_by_zone l
            LEFT JOIN wind_hourly_regional w USING (interval_ts, dst_flag)
            LEFT JOIN solar_hourly_regional s USING (interval_ts, dst_flag)
            WHERE l.interval_ts >= %s AND l.interval_ts < %s
              AND l.total IS NOT NULL
            GROUP BY 1
        )
        SELECT (l.interval_ts AT TIME ZONE 'America/Chicago')::date AS delivery_date,
               MAX(l.system_total) AS value,
               MAX(l.system_total - w.stwpf_system_wide - s.stppf_system_wide) AS net_load,
               MAX(a.actual_value) AS actual_value,
               MAX(a.actual_net_load) AS actual_net_load,
               -- Wind/solar averaged over the empirical high-congestion CT window
               -- (HIGH_CONGESTION_CT_HOURS): the renewable supply into the peak,
               -- ranked later to explain a congestion day the load level alone cannot.
               AVG(w.stwpf_system_wide) FILTER (
                 WHERE EXTRACT(hour FROM l.interval_ts AT TIME ZONE 'America/Chicago') IN (15, 16, 17, 18)
               ) AS wind_peak,
               AVG(s.stppf_system_wide) FILTER (
                 WHERE EXTRACT(hour FROM l.interval_ts AT TIME ZONE 'America/Chicago') IN (15, 16, 17, 18)
               ) AS solar_peak
        FROM load_vintaged l
        LEFT JOIN wind_vintaged w USING (interval_ts, dst_flag)
        LEFT JOIN solar_vintaged s USING (interval_ts, dst_flag)
        LEFT JOIN actual_daily a ON a.delivery_date =
          (l.interval_ts AT TIME ZONE 'America/Chicago')::date
        WHERE l.system_total IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """
    with conn.cursor() as cur:
        params = (start, end, start, end, start, end, start, end)
        cur.execute(sql, params)
        return _rows(cur, ("delivery_date", "value", "net_load", "actual_value",
                           "actual_net_load", "wind_peak", "solar_peak"))


def _trailing_pct(series: list[float | None], value: float | None) -> float | None:
    """Percentile rank of ``value`` within the non-null trailing series."""
    observed = [v for v in series if v is not None]
    if value is None or not observed:
        return None
    return 100.0 * sum(v <= value for v in observed) / len(observed)


def summarize_load_condition(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the raw condition values consumed by the regime classifier.

    Beyond the load percentile the regime slot carries the peak-window renewable
    supply percentiles and the settled forecast miss.  These do not change the
    regime bucket; they feed the lede's driver clause (see ``phrases.py``).
    """
    if not rows:
        return None
    values = [float(row["value"]) for row in rows]
    today = values[-1]
    last = rows[-1]

    def _series(column: str) -> list[float | None]:
        return [float(r[column]) if r.get(column) is not None else None for r in rows]

    wind_series, solar_series = _series("wind_peak"), _series("solar_peak")
    forecast = today
    actual = float(last["actual_value"]) if last.get("actual_value") is not None else None
    load_miss = (100.0 * (actual - forecast) / forecast
                 if actual is not None and forecast else None)
    return {
        "series": "load.system",
        "today": today,
        "net_load": (float(last["net_load"]) if last.get("net_load") is not None else None),
        "actual_today": actual,
        "actual_net_load": (float(last["actual_net_load"])
                             if last.get("actual_net_load") is not None else None),
        "median": float(median(values)),
        "pct": 100.0 * sum(value <= today for value in values) / len(values),
        "wind_peak": wind_series[-1],
        "solar_peak": solar_series[-1],
        "wind_pct": _trailing_pct(wind_series, wind_series[-1]),
        "solar_pct": _trailing_pct(solar_series, solar_series[-1]),
        "load_miss_pct": load_miss,
        "load_miss_abs": abs(load_miss) if load_miss is not None else None,
        "n": len(values),
        "basis": "forecast",
    }
