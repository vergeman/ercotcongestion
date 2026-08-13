"""Small, as-of trailing-window readers for the v6 hero.

These readers intentionally aggregate in Postgres rather than borrowing the SF
panel loaders, which pivot thousands of hourly columns before reducing them.
All end bounds are exclusive delivery-day boundaries in America/Chicago: a
re-run for a past day therefore cannot see a later backfill.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo


ERCOT_TZ = ZoneInfo("America/Chicago")
HIGH_CONGESTION_CT_HOURS = (15, 16, 17, 18)  # Empirical slice; not a market on-peak definition.


def delivery_bounds(delivery_date: date) -> tuple[datetime, datetime]:
    """Return the UTC [start, end) bounds for one ERCOT delivery day."""
    start = datetime.combine(delivery_date, datetime.min.time(), tzinfo=ERCOT_TZ)
    end = start + timedelta(days=1)
    return start.astimezone(ZoneInfo("UTC")), end.astimezone(ZoneInfo("UTC"))


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
    """Return each day's DAM-close-vintaged peak system-load forecast.

    The daily peak is an intelligible system-load condition and the query keeps
    only forecasts published by that delivery day's 10:00 CT DAM close.
    """
    start, end = delivery_bounds(delivery_date)
    start -= timedelta(days=days)
    sql = """
        WITH vintaged AS (
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
        )
        SELECT (interval_ts AT TIME ZONE 'America/Chicago')::date AS delivery_date,
               MAX(system_total) AS value
        FROM vintaged
        WHERE system_total IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (start, end))
        return _rows(cur, ("delivery_date", "value"))


def summarize_load_condition(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the raw condition values consumed by the regime classifier."""
    if not rows:
        return None
    values = [float(row["value"]) for row in rows]
    today = values[-1]
    return {
        "series": "load.system",
        "today": today,
        "median": float(median(values)),
        "pct": 100.0 * sum(value <= today for value in values) / len(values),
        "n": len(values),
        "basis": "forecast",
    }
