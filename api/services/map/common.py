"""Shared Map run, artifact, and geography queries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd
from fastapi import HTTPException

from api.config import MAP_RUN_ID
from api.services.sf_artifacts import coerce_utc, delivery_date_for, load_daily_artifact


def resolve(cur) -> tuple[str, object]:
    run_id = map_run_id(cur)

    cur.execute(
        "SELECT max(window_start) AS ws FROM sf_window_meta WHERE run_id = %s",
        (run_id,),
    )
    row = cur.fetchone()
    if row is None or row["ws"] is None:
        raise HTTPException(
            status_code=503,
            detail=f"no window built for run_id={run_id}.",
        )
    return run_id, row["ws"]


def map_run_id(cur) -> str:
    """Return the configured map run, or the newest run when unconfigured."""
    run_id = MAP_RUN_ID
    if run_id is None:
        cur.execute(
            "SELECT run_id FROM sf_window_meta ORDER BY window_start DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(
                status_code=503,
                detail="no SF run is built yet (sf_window_meta is empty).",
            )
        run_id = row["run_id"]

    return run_id


def meta_row(cur, run_id: str, window_start) -> dict:
    cur.execute(
        "SELECT run_id, window_start, window_end, sf_fit_r2, sf_oos_r2, coverage, "
        "sf_stability, n_kept FROM sf_window_meta "
        "WHERE run_id = %s AND window_start = %s",
        (run_id, window_start),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(
            status_code=503,
            detail=f"window {window_start} missing from sf_window_meta for {run_id}.",
        )
    return row


def forecast_run_id(cur) -> str:
    cur.execute("SELECT run_id FROM forecast_current WHERE layer = 'ercot'")
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=503, detail="no forecast run is published yet.")
    return str(row["run_id"])


def latest_artifact_day(cur, run_id: str):
    cur.execute(
        "SELECT max(delivery_date) AS d FROM forecast_sf_artifact WHERE run_id = %s",
        (run_id,),
    )
    row = cur.fetchone()
    return None if row is None else row["d"]


def nearest_past_artifact_day(cur, run_id: str, day):
    """Find the structural fallback for a missing requested-day artifact.

    Constraint reach changes slowly with topology, so the nearest earlier build
    is preferable to an empty card during a lagging or failed forecast job.
    """
    if day is None:
        return None
    cur.execute(
        "SELECT max(delivery_date) AS d FROM forecast_sf_artifact "
        "WHERE run_id = %s AND delivery_date <= %s",
        (run_id, day),
    )
    row = cur.fetchone()
    return None if row is None else row["d"]


@dataclass
class ArtifactProvenance:
    """The day artifact and causal SF window that produced its structure."""

    forecast_run_id: str
    requested_delivery_date: date | None
    artifact_delivery_date: date | None
    basis: str
    artifact: object | None
    map_run_id: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None


def resolve_artifact_provenance(
    cur,
    t: datetime | None = None,
    *,
    delivery_day: date | None = None,
    nearest_past: bool = True,
) -> ArtifactProvenance:
    """Resolve a cursor's artifact and the SF window causal to that artifact.

    The artifact table predates explicit map-window columns. Its producer chose
    the newest window ending on or before the delivery day; replay that rule
    rather than reading today's newest window.
    """
    forecast_run = forecast_run_id(cur)
    requested_day = (
        delivery_date_for(t)
        if t is not None
        else delivery_day or latest_artifact_day(cur, forecast_run)
    )
    artifact_day = requested_day
    artifact = (
        load_daily_artifact(cur, forecast_run, artifact_day)
        if artifact_day is not None
        else None
    )
    basis = "artifact"
    if artifact is None and nearest_past:
        artifact_day = nearest_past_artifact_day(cur, forecast_run, requested_day)
        artifact = (
            load_daily_artifact(cur, forecast_run, artifact_day)
            if artifact_day is not None
            else None
        )
        basis = "nearest_past"
    result = ArtifactProvenance(
        forecast_run, requested_day, artifact_day if artifact is not None else None,
        basis, artifact,
    )
    if artifact is None:
        return result

    cur.execute(
        "SELECT sf_map_run_id, sf_window_start, sf_window_end "
        "FROM forecast_sf_artifact WHERE run_id = %s AND delivery_date = %s "
        "ORDER BY horizon LIMIT 1",
        (forecast_run, artifact_day),
    )
    row = cur.fetchone()
    if row is not None and row.get("sf_map_run_id") is not None:
        result.map_run_id = row["sf_map_run_id"]
        result.window_start, result.window_end = row["sf_window_start"], row["sf_window_end"]
        return result

    result.map_run_id = map_run_id(cur)
    cur.execute(
        "SELECT window_start, window_end FROM sf_window_meta "
        "WHERE run_id = %s AND window_end <= %s ORDER BY window_start DESC LIMIT 1",
        (result.map_run_id, artifact_day),
    )
    row = cur.fetchone()
    if row is not None:
        result.window_start, result.window_end = row["window_start"], row["window_end"]
    return result


def click_artifact(cur, t: datetime | None):
    """Resolve the forecast artifact for a map click.

    ``t`` maps to its CT delivery day, not its UTC date, so Map and Matrix read
    the same day artifact for evening hours.
    """
    run_id = forecast_run_id(cur)
    day = delivery_date_for(t) if t is not None else latest_artifact_day(cur, run_id)
    if day is None:
        return run_id, None, None
    return run_id, day, load_daily_artifact(cur, run_id, day)


def interval_in_artifact(artifact, t: datetime | None) -> bool:
    """Keep Map unavailable when the requested interval is absent from its block.

    This prevents a Map/Matrix disagreement for a partial or misaligned
    artifact.
    """
    return t is None or pd.Timestamp(coerce_utc(t)) in artifact.E_mu.index


def artifact_window(artifact) -> tuple[datetime, datetime]:
    idx = artifact.E_mu.index
    return idx.min().to_pydatetime(), idx.max().to_pydatetime()


def hour_mu(artifact, t: datetime | None) -> pd.Series:
    """Return the selected interval's forecast μ, or the whole-block roll-up."""
    return (
        artifact.E_mu.sum(axis=0)
        if t is None
        else artifact.E_mu.loc[pd.Timestamp(coerce_utc(t))]
    )


def geo_metadata(cur, constraint_keys: list[str]) -> dict[str, dict]:
    """Read structural fields from the newest geo window, not daily magnitudes."""
    if not constraint_keys:
        return {}
    cur.execute(
        "SELECT DISTINCT ON (constraint_key) constraint_key, ctype, n_rail, peak_offrail "
        "FROM constraint_geo WHERE constraint_key = ANY(%s) "
        "ORDER BY constraint_key, window_start DESC",
        (constraint_keys,),
    )
    return {str(row["constraint_key"]): row for row in cur.fetchall()}
