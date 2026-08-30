"""Shared Map run, artifact, and geography queries."""
from __future__ import annotations

from datetime import datetime
import pandas as pd
from fastapi import HTTPException

from config import MAP_RUN_ID
from services.sf_artifacts import coerce_utc, delivery_date_for, load_daily_artifact

def resolve(cur) -> tuple[str, object]:
    run_id = MAP_RUN_ID
    if run_id is None:
        cur.execute("SELECT run_id FROM sf_window_meta ORDER BY window_start DESC LIMIT 1")
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=503, detail="no SF run is built yet (sf_window_meta is empty).")
        run_id = row["run_id"]
    cur.execute("SELECT max(window_start) AS ws FROM sf_window_meta WHERE run_id = %s", (run_id,))
    row = cur.fetchone()
    if row is None or row["ws"] is None:
        raise HTTPException(status_code=503, detail=f"no window built for run_id={run_id}.")
    return run_id, row["ws"]

def meta_row(cur, run_id: str, window_start) -> dict:
    cur.execute("SELECT run_id, window_start, window_end, fit_r2, oos_r2, coverage, sf_stability, n_kept FROM sf_window_meta WHERE run_id = %s AND window_start = %s", (run_id, window_start))
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=503, detail=f"window {window_start} missing from sf_window_meta for {run_id}.")
    return row

def forecast_run_id(cur) -> str:
    cur.execute("SELECT run_id FROM forecast_current WHERE layer = 'ercot'")
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=503, detail="no forecast run is published yet.")
    return str(row["run_id"])

def latest_artifact_day(cur, run_id: str):
    cur.execute("SELECT max(delivery_date) AS d FROM forecast_sf_artifact WHERE run_id = %s", (run_id,))
    row = cur.fetchone()
    return None if row is None else row["d"]

def nearest_past_artifact_day(cur, run_id: str, day):
    if day is None:
        return None
    cur.execute("SELECT max(delivery_date) AS d FROM forecast_sf_artifact WHERE run_id = %s AND delivery_date <= %s", (run_id, day))
    row = cur.fetchone()
    return None if row is None else row["d"]

def click_artifact(cur, t: datetime | None):
    run_id = forecast_run_id(cur)
    day = delivery_date_for(t) if t is not None else latest_artifact_day(cur, run_id)
    if day is None:
        return run_id, None, None
    return run_id, day, load_daily_artifact(cur, run_id, day)

def interval_in_artifact(artifact, t: datetime | None) -> bool:
    return t is None or pd.Timestamp(coerce_utc(t)) in artifact.E_mu.index

def artifact_window(artifact) -> tuple[datetime, datetime]:
    idx = artifact.E_mu.index
    return idx.min().to_pydatetime(), idx.max().to_pydatetime()

def hour_mu(artifact, t: datetime | None) -> pd.Series:
    return artifact.E_mu.sum(axis=0) if t is None else artifact.E_mu.loc[pd.Timestamp(coerce_utc(t))]

def geo_metadata(cur, constraint_keys: list[str]) -> dict[str, dict]:
    if not constraint_keys:
        return {}
    cur.execute("SELECT DISTINCT ON (constraint_key) constraint_key, ctype, n_rail, peak_offrail FROM constraint_geo WHERE constraint_key = ANY(%s) ORDER BY constraint_key, window_start DESC", (constraint_keys,))
    return {str(row["constraint_key"]): row for row in cur.fetchall()}
