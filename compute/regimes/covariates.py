"""Per-hour ERCOT system covariates: load, wind, solar, system_lambda.

Aligned to a matrix ``hours`` axis (values shaped ``regime|iso`` — the
same encoding written by ``compute.matrix``). Reads existing ERCOT
tables in Postgres:

* ``load_by_zone``            — 15-min per-zone loads; summed across
                                zones and averaged into hour-ending.
* ``wind_hourly_regional``    — hourly, ``gen_system_wide`` column.
* ``solar_hourly_regional``   — hourly, ``gen_system_wide`` column.
* ``dam_system_lambda``       — hourly, ``system_lambda`` column.

Missing rows produce NaN in the output vector rather than raising, so
one absent source doesn't disqualify the other schemes. The caller is
expected to log which schemes become unavailable.
"""
from __future__ import annotations

import logging
from datetime import datetime

import numpy as np
import psycopg

from compute.config import PG_DSN
from compute.ercot.transforms import WEATHER_ZONES

logger = logging.getLogger(__name__)

COVARIATE_KEYS = ("load", "wind", "solar", "system_lambda")


def parse_hours(hours: np.ndarray) -> list[datetime]:
    """Parse matrix ``hours`` strings (``regime|iso`` or plain ISO) to
    tz-aware ``datetime`` objects."""
    out: list[datetime] = []
    for raw in hours.tolist():
        s = str(raw)
        if "|" in s:
            s = s.split("|", 1)[1]
        out.append(datetime.fromisoformat(s))
    return out


def load_hourly_covariates(
    hours: np.ndarray,
    *,
    conn: "psycopg.Connection | None" = None,
) -> tuple[dict[str, np.ndarray], list[str]]:
    """Fetch per-hour covariate vectors aligned to ``hours``.

    Returns ``(covariates, missing_sources)`` where ``covariates`` maps
    each key in :data:`COVARIATE_KEYS` to a length-``n_hours`` float
    array (NaN for hours with no row), and ``missing_sources`` lists
    keys that came back all-NaN.
    """
    ts_list = parse_hours(hours)
    n = len(ts_list)

    if conn is None:
        with psycopg.connect(PG_DSN) as owned:
            return _load_with_conn(owned, ts_list, n)
    return _load_with_conn(conn, ts_list, n)


def _load_with_conn(
    conn: "psycopg.Connection",
    ts_list: list[datetime],
    n: int,
) -> tuple[dict[str, np.ndarray], list[str]]:
    load = _fetch_total_load(conn, ts_list)
    wind = _fetch_gen(conn, ts_list, "wind_hourly_regional")
    solar = _fetch_gen(conn, ts_list, "solar_hourly_regional")
    sysl = _fetch_system_lambda(conn, ts_list)

    covariates: dict[str, np.ndarray] = {
        "load": _align(ts_list, load, n),
        "wind": _align(ts_list, wind, n),
        "solar": _align(ts_list, solar, n),
        "system_lambda": _align(ts_list, sysl, n),
    }
    missing = [k for k, v in covariates.items() if not np.isfinite(v).any()]
    for k in missing:
        logger.warning(
            "regime covariate %r is all-NaN across the requested window", k,
        )
    return covariates, missing


def _fetch_total_load(
    conn: "psycopg.Connection",
    ts_list: list[datetime],
) -> dict[datetime, float]:
    """Sum ``load_by_zone`` across ERCOT weather zones and average within
    each hour-ending timestamp (mirrors ``fetch_zone_loads_batch``)."""
    cols = " + ".join(f"COALESCE(AVG({z}), 0)" for z in WEATHER_ZONES)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT interval_ts, {cols} AS total_load
            FROM load_by_zone
            WHERE interval_ts = ANY(%s)
            GROUP BY interval_ts
            """,
            (ts_list,),
        )
        return {ts: float(v) for ts, v in cur.fetchall()}


def _fetch_gen(
    conn: "psycopg.Connection",
    ts_list: list[datetime],
    table: str,
) -> dict[datetime, float]:
    """One ``gen_system_wide`` per timestamp; ``dst_flag=ASC`` on ties
    mirrors the ERCOT DAM fetcher pattern."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT ON (interval_ts) interval_ts, gen_system_wide
            FROM {table}
            WHERE interval_ts = ANY(%s)
            ORDER BY interval_ts, dst_flag ASC
            """,
            (ts_list,),
        )
        return {
            ts: (float(v) if v is not None else float("nan"))
            for ts, v in cur.fetchall()
        }


def _fetch_system_lambda(
    conn: "psycopg.Connection",
    ts_list: list[datetime],
) -> dict[datetime, float]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (interval_ts) interval_ts, system_lambda
            FROM dam_system_lambda
            WHERE interval_ts = ANY(%s)
            ORDER BY interval_ts, dst_flag ASC
            """,
            (ts_list,),
        )
        return {ts: float(v) for ts, v in cur.fetchall()}


def _align(
    ts_list: list[datetime],
    by_ts: dict[datetime, float],
    n: int,
) -> np.ndarray:
    out = np.full(n, np.nan, dtype=float)
    for i, ts in enumerate(ts_list):
        v = by_ts.get(ts)
        if v is not None:
            out[i] = v
    return out
