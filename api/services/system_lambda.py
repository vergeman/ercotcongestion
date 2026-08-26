"""Shared DAM system-lambda lookup and forecast display fallback."""
from __future__ import annotations

from datetime import datetime
from services.time import CENTRAL, coerce_utc


def settled_system_lambdas(cur, start: datetime, end: datetime) -> dict[datetime, float | None]:
    """Return the published DAM lambda at each instant in an inclusive window."""
    cur.execute(
        """
        SELECT DISTINCT ON (interval_ts) interval_ts, system_lambda
        FROM dam_system_lambda
        WHERE interval_ts >= %s AND interval_ts <= %s
        ORDER BY interval_ts, dst_flag ASC
        """,
        (start, end),
    )
    return {
        coerce_utc(row["interval_ts"]): (
            None if row["system_lambda"] is None else float(row["system_lambda"])
        )
        for row in cur.fetchall()
    }


def persisted_system_lambdas_by_ct_hour(cur) -> dict[int, float]:
    """Most recent settled CT-day lambda curve used for forecast display only."""
    cur.execute(
        """
        SELECT DISTINCT ON (interval_ts) interval_ts, system_lambda
        FROM dam_system_lambda
        WHERE (interval_ts AT TIME ZONE 'America/Chicago')::date = (
            SELECT (interval_ts AT TIME ZONE 'America/Chicago')::date
            FROM dam_system_lambda
            ORDER BY interval_ts DESC
            LIMIT 1
        )
        ORDER BY interval_ts, dst_flag ASC
        """
    )
    values: dict[int, float] = {}
    for row in cur.fetchall():
        if row["system_lambda"] is None:
            continue
        values.setdefault(
            coerce_utc(row["interval_ts"]).astimezone(CENTRAL).hour,
            float(row["system_lambda"]),
        )
    return values


def forecast_system_lambda(
    timestamp: datetime,
    settled_by_ts: dict[datetime, float | None],
    persisted_by_ct_hour: dict[int, float],
) -> tuple[float | None, str | None]:
    """Return the forecast LMP reference and whether it is settled or persisted."""
    ts = coerce_utc(timestamp)
    settled = settled_by_ts.get(ts)
    if settled is not None:
        return settled, "settled"
    persisted = persisted_by_ct_hour.get(ts.astimezone(CENTRAL).hour)
    if persisted is not None:
        return persisted, "persisted"
    return None, None
