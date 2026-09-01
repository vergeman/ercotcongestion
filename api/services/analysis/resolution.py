"""Shared Analysis selection and artifact availability policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd
from fastapi import HTTPException

from compute.time import delivery_bounds


@dataclass(frozen=True)
class ArtifactSelection:
    run_id: str
    delivery_date: date
    horizon: int | None


def resolve_run(cur, run_id: str | None) -> str:
    if run_id is not None:
        return run_id
    cur.execute("SELECT run_id FROM forecast_current WHERE layer = 'ercot'")
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=503, detail="no forecast run is published yet.")
    return str(row["run_id"])


def resolve_horizon(
    cur, run_id: str, delivery_date: date, horizon: int | None
) -> int | None:
    if horizon is not None:
        return horizon
    cur.execute(
        "SELECT min(horizon) AS h FROM forecast_sf_artifact "
        "WHERE run_id = %s AND delivery_date = %s",
        (run_id, delivery_date),
    )
    row = cur.fetchone()
    return None if row is None or row["h"] is None else int(row["h"])


def resolve_delivery_date(delivery_date: date | None, legacy_day: date | None) -> date:
    delivery_date = delivery_date if isinstance(delivery_date, date) else None
    legacy_day = legacy_day if isinstance(legacy_day, date) else None
    if delivery_date is None:
        delivery_date = legacy_day
    elif legacy_day is not None and legacy_day != delivery_date:
        raise HTTPException(
            status_code=422, detail="delivery_date and deprecated day must match."
        )
    if delivery_date is None:
        raise HTTPException(
            status_code=422, detail="delivery_date is required (deprecated alias: day)."
        )
    return delivery_date


def selected_hours(artifact, hours: list[datetime] | None) -> pd.DatetimeIndex:
    available = artifact.E_mu.index
    if hours is None:
        return available
    selected = pd.DatetimeIndex(pd.to_datetime(hours, utc=True))
    missing = selected.difference(available)
    if len(missing):
        raise HTTPException(
            status_code=422,
            detail="hours must be artifact timestamps for this delivery day.",
        )
    return selected.unique().sort_values()


def dam_landed(cur, delivery_date: date) -> bool:
    start, end = delivery_bounds(delivery_date)
    cur.execute(
        "SELECT max(interval_ts) AS ts FROM ercot_dam_shadow_prices "
        "WHERE interval_ts >= %s AND interval_ts < %s AND dst_flag = FALSE "
        "AND shadow_price IS NOT NULL",
        (start, end),
    )
    row = cur.fetchone()
    return (
        row is not None
        and row["ts"] is not None
        and row["ts"] >= start + (end - start) / 2
    )
