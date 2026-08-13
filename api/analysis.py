"""GET /analysis/brief — the server-computed daily Insight Brief.

Read-only surface over ``analysis_brief`` (0124): the daily_brief job computes
one JSON brief per (run_id, delivery_date, horizon) from the served SF+μ̂
artifact; this endpoint hands it back verbatim. The disabled Analysis nav item
is its home (docs/last_mile.md). Nothing is computed here — a day with no brief
yet returns ``available=false`` rather than 404, matching the Matrix's soft-fail
contract so the UI can render an empty state.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from db import get_pool
from models import (HeroAvailableResponse, HeroUnavailableAtHorizonResponse,
                    HeroUnavailableResponse)
from compute.analysis.hero import magnitude_verdict
from compute.analysis.hero_builder import build_hero
from compute.analysis.hero_window import delivery_bounds
from compute.analysis.phrases import render
from services.sf_artifacts import load_daily_artifact

router = APIRouter(prefix="/analysis")


def _iso_z(value) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _cursor(delivery_date: date, artifact) -> dict[str, str]:
    """Delivery-day bounds plus the artifact's largest forecast-μ hour."""
    ws, we = delivery_bounds(delivery_date)
    peak = artifact.E_mu.abs().sum(axis=1).idxmax()
    return {"ws": _iso_z(ws), "we": _iso_z(we), "t": _iso_z(peak)}


def _dam_landed(cur, delivery_date: date) -> bool:
    """Require a substantive part of the day, not only the prior CT-day tail."""
    ws, we = delivery_bounds(delivery_date)
    cur.execute(
        "SELECT max(interval_ts) AS ts FROM ercot_dam_shadow_prices "
        "WHERE interval_ts >= %s AND interval_ts < %s AND dst_flag = FALSE "
        "AND shadow_price IS NOT NULL",
        (ws, we),
    )
    row = cur.fetchone()
    return row is not None and row["ts"] is not None and row["ts"] >= ws + (we - ws) / 2


def _verdicts(forecast: dict, settled: dict) -> dict[str, dict | None]:
    """Grade slots independently; condition data has no actual counterpart."""
    return {
        "magnitude": magnitude_verdict(forecast["magnitude"], settled["magnitude"]),
        "regime": None,
        "where": {"bucket": "held" if forecast["where"].get("zone") == settled["where"].get("zone")
                  else "shifted"},
        "exceptions": {"bucket": "held" if forecast["exceptions"].get("bucket")
                       == settled["exceptions"].get("bucket") else "shifted"},
    }


@router.get("/hero", response_model=(HeroAvailableResponse | HeroUnavailableResponse |
                                      HeroUnavailableAtHorizonResponse),
            summary="Server-computed v6 daily-brief hero")
def get_hero(
    delivery_date: date = Query(..., alias="date", description="ERCOT delivery day."),
    run_id: str | None = Query(None, description="Model version; defaults to the published run."),
    horizon: int | None = Query(None, ge=1, le=2, description="Artifact track; final preferred."),
) -> HeroAvailableResponse | HeroUnavailableResponse | HeroUnavailableAtHorizonResponse:
    """Return prose segments, raw slots, independent verdicts, and map cursor."""
    # All window reads below share this checked-out connection.  Do not release
    # it before ``build_hero``: it performs the on-demand query layer itself.
    with get_pool().connection() as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            if run_id is None:
                cur.execute("SELECT run_id FROM forecast_current WHERE layer = 'ercot'")
                row = cur.fetchone()
                if row is None:
                    raise HTTPException(status_code=503, detail="no forecast run is published yet.")
                run_id = str(row["run_id"])
            if horizon is None:
                cur.execute(
                    "SELECT min(horizon) AS h FROM forecast_sf_artifact "
                    "WHERE run_id = %s AND delivery_date = %s", (run_id, delivery_date))
                row = cur.fetchone()
                if row is None or row["h"] is None:
                    return {"available": False, "unavailable_reason": "artifact_missing",
                            "run_id": run_id, "delivery_date": delivery_date}
                horizon = int(row["h"])
            artifact = load_daily_artifact(cur, run_id, delivery_date, horizon)
            settled = _dam_landed(cur, delivery_date)

        if artifact is None:
            return {"available": False, "unavailable_reason": "artifact_missing", "run_id": run_id,
                    "delivery_date": delivery_date, "horizon": horizon}
        basis = "settled" if settled else "forecast"
        slots = build_hero(conn, run_id, delivery_date, horizon, basis, artifact=artifact)
        verdict = None
        if settled:
            forecast = build_hero(conn, run_id, delivery_date, horizon, "forecast", artifact=artifact)
            verdict = _verdicts(forecast, slots)
        return {
            "available": True,
            "segments": render(slots),
            "slots": slots,
            "verdict": verdict,
            "cursor": _cursor(delivery_date, artifact),
            "provenance": {"run_id": run_id, "delivery_date": delivery_date,
                           "horizon": horizon, "basis": basis},
        }


@router.get("/brief", summary="Server-computed daily Insight Brief")
def get_brief(
    delivery_date: date = Query(..., description="Delivery day (UTC calendar date)."),
    run_id: str | None = Query(None, description="Model version; defaults to the "
                               "currently published ercot run."),
    horizon: int | None = Query(None, ge=1, le=2, description="Artifact track; "
                                "defaults to the served horizon (final, else preview)."),
) -> dict:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        if run_id is None:
            cur.execute("SELECT run_id FROM forecast_current WHERE layer = 'ercot'")
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=503, detail="no forecast run is published yet.")
            run_id = str(row["run_id"])

        # Coalesce the horizon the same way the artifact lookup does: serve the
        # final brief when one exists, else the preview.
        if horizon is None:
            cur.execute(
                "SELECT min(horizon) AS h FROM analysis_brief "
                "WHERE run_id = %s AND delivery_date = %s",
                (run_id, delivery_date),
            )
            row = cur.fetchone()
            if row is None or row["h"] is None:
                return {"available": False, "unavailable_reason": "brief_missing",
                        "run_id": run_id, "delivery_date": delivery_date}
            horizon = int(row["h"])

        cur.execute(
            "SELECT brief, horizon, computed_at FROM analysis_brief "
            "WHERE run_id = %s AND delivery_date = %s AND horizon = %s",
            (run_id, delivery_date, horizon),
        )
        row = cur.fetchone()

    if row is None:
        return {"available": False, "unavailable_reason": "brief_missing",
                "run_id": run_id, "delivery_date": delivery_date, "horizon": horizon}

    return {
        "available": True,
        "run_id": run_id,
        "delivery_date": delivery_date,
        "horizon": int(row["horizon"]),
        "computed_at": row["computed_at"],
        "brief": row["brief"],
    }


@router.get("/brief/latest", summary="Latest day's Insight Brief + the day index")
def get_brief_latest(
    run_id: str | None = Query(None, description="Model version; defaults to the "
                               "currently published ercot run."),
) -> dict:
    """The most recent day's full brief, plus the run's ``available_dates`` index.

    Resolves the run the same way ``GET /analysis/brief`` does, picks the latest
    ``delivery_date`` that has a brief, and returns that day's brief in the same
    envelope the per-day endpoint uses — coalescing the served horizon (final,
    else preview) exactly as the sibling does. ``available_dates`` is the sorted
    list of every delivery day with a brief for the run: the page derives prev/next
    as array neighbors (gaps skipped) and fetches each day through the frozen
    per-day endpoint. ``available=false`` (not 404) when the run has no brief yet.
    """
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        if run_id is None:
            cur.execute("SELECT run_id FROM forecast_current WHERE layer = 'ercot'")
            row = cur.fetchone()
            if row is None:
                raise HTTPException(status_code=503, detail="no forecast run is published yet.")
            run_id = str(row["run_id"])

        # The run's day index (dates only — cheap). Neighbors of this sorted list
        # are what the page steps through, so gaps in history are skipped.
        cur.execute(
            "SELECT DISTINCT delivery_date FROM analysis_brief "
            "WHERE run_id = %s ORDER BY delivery_date",
            (run_id,),
        )
        available_dates = [r["delivery_date"] for r in cur.fetchall()]
        if not available_dates:
            return {"available": False, "unavailable_reason": "brief_missing",
                    "run_id": run_id, "available_dates": []}

        delivery_date = available_dates[-1]

        # Coalesce the served horizon for the latest day: final (min horizon) wins.
        cur.execute(
            "SELECT brief, horizon, computed_at FROM analysis_brief "
            "WHERE run_id = %s AND delivery_date = %s ORDER BY horizon LIMIT 1",
            (run_id, delivery_date),
        )
        row = cur.fetchone()

    return {
        "available": True,
        "run_id": run_id,
        "delivery_date": delivery_date,
        "horizon": int(row["horizon"]),
        "computed_at": row["computed_at"],
        "brief": row["brief"],
        "available_dates": available_dates,
    }
