"""Forecast congestion range query service."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from psycopg.rows import dict_row

from db import get_pool
from schemas.forecast import ForecastRangeEntry, ForecastRangeResponse, ForecastSpState
from services.system_lambda import (
    forecast_system_lambda,
    persisted_system_lambdas_by_ct_hour,
    settled_system_lambdas,
)
from services.time import coerce_utc


def _round_congestion(value: float | None) -> float | None:
    if value is None:
        return None
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def forecast_range(
    run_id: str | None,
    start: datetime | None,
    end: datetime | None,
    horizon: int | None,
) -> ForecastRangeResponse:
    """Return forecast congestion for a normalized optional interval."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        if run_id is None:
            cur.execute("SELECT run_id FROM forecast_current WHERE layer = 'ercot'")
            row = cur.fetchone()
            if row is None:
                raise HTTPException(
                    status_code=503,
                    detail="no forecast run is published yet (forecast_current is empty).",
                )
            run_id = row["run_id"]

        hz_clause = "" if horizon is None else " AND horizon = %s"
        hz_args: tuple = () if horizon is None else (horizon,)
        if start is not None and end is not None:
            start_u, end_u = start, end
        else:
            cur.execute(
                f"""
                SELECT MIN(ts) AS lo, MAX(ts) AS hi
                FROM forecast_nodal
                WHERE run_id = %s{hz_clause} AND delivery_date = (
                    SELECT MAX(delivery_date)
                    FROM forecast_nodal WHERE run_id = %s{hz_clause}
                )
                """,
                (run_id, *hz_args, run_id, *hz_args),
            )
            span = cur.fetchone()
            if span is None or span["lo"] is None:
                raise HTTPException(
                    status_code=404 if horizon is not None else 503,
                    detail=(
                        f"run_id={run_id}"
                        + (f" horizon={horizon}" if horizon is not None else "")
                        + " has no forecast_nodal rows to default a window from."
                    ),
                )
            start_u, end_u = coerce_utc(span["lo"]), coerce_utc(span["hi"])

        cur.execute(
            f"""
            SELECT DISTINCT ON (ts, settlement_point)
                   ts, settlement_point, point AS forecast_congestion,
                   delivery_date, horizon
            FROM forecast_nodal
            WHERE run_id = %s AND ts >= %s AND ts <= %s{hz_clause}
            ORDER BY ts, settlement_point, horizon ASC
            """,
            (run_id, start_u, end_u, *hz_args),
        )
        rows = cur.fetchall()
        lam_by_ts_raw = settled_system_lambdas(cur, start_u, end_u)
        unsettled = {
            coerce_utc(row["ts"])
            for row in rows
            if coerce_utc(row["ts"]) not in lam_by_ts_raw
        }
        persisted_by_hour = persisted_system_lambdas_by_ct_hour(cur) if unsettled else {}

    if not rows:
        raise HTTPException(
            status_code=404 if horizon is not None else 503,
            detail=(
                f"no forecast_nodal rows for run_id={run_id}"
                + (f" horizon={horizon}" if horizon is not None else "")
                + f" in window {start_u} .. {end_u}. The served forecast run has no hours here."
            ),
        )

    horizons: dict[str, int] = {}
    by_ts: dict[datetime, list[ForecastSpState]] = {}
    for row in rows:
        ts = coerce_utc(row["ts"])
        horizons[row["delivery_date"].isoformat()] = int(row["horizon"])
        by_ts.setdefault(ts, []).append(
            ForecastSpState(
                sp_id=str(row["settlement_point"]),
                forecast_congestion=_round_congestion(row["forecast_congestion"]),
            )
        )

    entries = []
    for ts, sps in sorted(by_ts.items()):
        system_lambda, lambda_source = forecast_system_lambda(
            ts, lam_by_ts_raw, persisted_by_hour
        )
        entries.append(
            ForecastRangeEntry(
                interval_ts=ts,
                system_lambda=system_lambda,
                lambda_source=lambda_source,
                sps=sps,
            )
        )
    return ForecastRangeResponse(
        start=start_u,
        end=end_u,
        run_id=run_id,
        count=len(entries),
        entries=entries,
        horizons=horizons,
    )
