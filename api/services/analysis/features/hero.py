"""Hero feature service for the daily Analysis Brief."""

from __future__ import annotations

from datetime import date
import logging
from time import perf_counter

from fastapi import HTTPException
from psycopg.rows import dict_row

from api.db import get_pool
from api.services.analysis.resolution import dam_landed, resolve_delivery_date
from api.services.sf_artifacts import load_daily_artifact
from compute.analysis.hero import magnitude_verdict
from compute.analysis.hero_builder import build_hero
from compute.time import delivery_bounds
from compute.analysis.phrases import render

logger = logging.getLogger(__name__)
_SLOW_REQUEST_SECONDS = 1.0


def _iso_z(value) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _cursor(delivery_date: date, artifact) -> dict[str, str]:
    window_start, window_end = delivery_bounds(delivery_date)
    peak = artifact.E_mu.abs().sum(axis=1).idxmax()
    return {"ws": _iso_z(window_start), "we": _iso_z(window_end), "t": _iso_z(peak)}


def _verdicts(forecast: dict, settled: dict) -> dict[str, dict | None]:
    return {
        "magnitude": magnitude_verdict(forecast["magnitude"], settled["magnitude"]),
        "regime": None,
        "where": {"bucket": "held" if forecast["where"].get("zone") == settled["where"].get("zone") else "shifted"},
        "exceptions": {"bucket": "held" if forecast["exceptions"].get("bucket") == settled["exceptions"].get("bucket") else "shifted"},
    }


def latest(run_id: str | None) -> dict:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        if run_id is None:
            cur.execute("SELECT run_id FROM forecast_current WHERE layer = 'ercot'")
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=503, detail="no forecast run is published yet.")
            run_id = str(row["run_id"])
        cur.execute(
            "SELECT delivery_date, horizon FROM forecast_sf_artifact WHERE run_id = %s "
            "ORDER BY delivery_date DESC, horizon ASC LIMIT 1",
            (run_id,),
        )
        row = cur.fetchone()
    if row is None:
        return {"available": False, "run_id": run_id}
    return {"available": True, "run_id": run_id, "delivery_date": row["delivery_date"], "horizon": int(row["horizon"])}


def get(
    delivery_date: date | None,
    run_id: str | None,
    horizon: int | None,
    *,
    legacy_day: date | None = None,
    include_condition: bool = True,
) -> dict:
    """Build the Brief hero without coupling the feature to FastAPI inputs."""
    delivery_date = resolve_delivery_date(delivery_date, legacy_day)
    started = perf_counter()
    with get_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            if run_id is None:
                cur.execute("SELECT run_id FROM forecast_current WHERE layer = 'ercot'")
                row = cur.fetchone()
                if row is None:
                    raise HTTPException(status_code=503, detail="no forecast run is published yet.")
                run_id = str(row["run_id"])
            if horizon is None:
                cur.execute("SELECT min(horizon) AS h FROM forecast_sf_artifact WHERE run_id = %s AND delivery_date = %s", (run_id, delivery_date))
                row = cur.fetchone()
                if row is None or row["h"] is None:
                    return {"available": False, "unavailable_reason": "artifact_missing", "run_id": run_id, "delivery_date": delivery_date}
                horizon = int(row["h"])
            artifact = load_daily_artifact(cur, run_id, delivery_date, horizon)
            settled = dam_landed(cur, delivery_date)
        if artifact is None:
            return {"available": False, "unavailable_reason": "artifact_missing", "run_id": run_id, "delivery_date": delivery_date, "horizon": horizon}
        basis = "settled" if settled else "forecast"
        slots = build_hero(conn, run_id, delivery_date, horizon, basis, artifact=artifact, include_condition=include_condition)
        verdict = None
        if settled:
            forecast = build_hero(conn, run_id, delivery_date, horizon, "forecast", artifact=artifact, include_condition=include_condition)
            verdict = _verdicts(forecast, slots)
    elapsed = perf_counter() - started
    if elapsed >= _SLOW_REQUEST_SECONDS:
        logger.info("hero_request_profile day=%s run=%s horizon=%s basis=%s total=%.3fs", delivery_date, run_id, horizon, basis, elapsed)
    return {"available": True, "segments": render(slots), "slots": slots, "verdict": verdict, "cursor": _cursor(delivery_date, artifact), "provenance": {"run_id": run_id, "delivery_date": delivery_date, "horizon": horizon, "basis": basis}}
