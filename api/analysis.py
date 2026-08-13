"""GET /analysis/brief — the server-computed daily Insight Brief.

Read-only surface over ``analysis_brief`` (0124): the daily_brief job computes
one JSON brief per (run_id, delivery_date, horizon) from the served SF+μ̂
artifact; this endpoint hands it back verbatim. The disabled Analysis nav item
is its home (docs/last_mile.md). Nothing is computed here — a day with no brief
yet returns ``available=false`` rather than 404, matching the Matrix's soft-fail
contract so the UI can render an empty state.
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Query
import pandas as pd
from psycopg.rows import dict_row

from db import get_pool
from models import (AnalysisContributionTerm, HeroAvailableResponse,
                    HeroUnavailableAtHorizonResponse, HeroUnavailableResponse,
                    NodeAnalysisAvailableResponse, NodeAnalysisUnavailableResponse,
                    PathAnalysisAvailableResponse, PathAnalysisUnavailableResponse,
                    PathComposition)
from compute.analysis.hero import magnitude_verdict
from compute.analysis.hero_builder import build_hero
from compute.analysis.hero_window import delivery_bounds
from compute.analysis.phrases import render
from compute.analysis.brief import pair_contributions
from compute.sf.project import node_contributions
from services.sf_artifacts import load_daily_artifact, load_realized_mu

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


def _resolve_run(cur, run_id: str | None) -> str:
    if run_id is not None:
        return run_id
    cur.execute("SELECT run_id FROM forecast_current WHERE layer = 'ercot'")
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=503, detail="no forecast run is published yet.")
    return str(row["run_id"])


def _resolve_horizon(cur, run_id: str, delivery_date: date, horizon: int | None) -> int | None:
    if horizon is not None:
        return horizon
    cur.execute(
        "SELECT min(horizon) AS h FROM forecast_sf_artifact "
        "WHERE run_id = %s AND delivery_date = %s", (run_id, delivery_date))
    row = cur.fetchone()
    return None if row is None or row["h"] is None else int(row["h"])


def _selected_hours(artifact, hours: list[datetime] | None) -> pd.DatetimeIndex:
    available = artifact.E_mu.index
    if hours is None:
        return available
    selected = pd.DatetimeIndex(pd.to_datetime(hours, utc=True))
    missing = selected.difference(available)
    if len(missing):
        raise HTTPException(status_code=422, detail="hours must be artifact timestamps for this delivery day.")
    return selected.unique().sort_values()


def _settled_congestion(cur, settlement_points: list[str], timestamps: pd.DatetimeIndex) -> dict[str, float]:
    params = (list(timestamps.to_pydatetime()), settlement_points)
    cur.execute(
        "SELECT DISTINCT ON (interval_ts, settlement_point) interval_ts, settlement_point, dam_spp "
        "FROM ercot_dam_spp WHERE interval_ts = ANY(%s) AND settlement_point = ANY(%s) "
        "ORDER BY interval_ts, settlement_point, dst_flag ASC", params)
    spp = {(row["interval_ts"], str(row["settlement_point"])): row["dam_spp"] for row in cur.fetchall()}
    cur.execute(
        "SELECT DISTINCT ON (interval_ts) interval_ts, system_lambda FROM dam_system_lambda "
        "WHERE interval_ts = ANY(%s) ORDER BY interval_ts, dst_flag ASC",
        (list(timestamps.to_pydatetime()),))
    lam = {row["interval_ts"]: row["system_lambda"] for row in cur.fetchall()}
    out = {sp: 0.0 for sp in settlement_points}
    complete = {sp: True for sp in settlement_points}
    for ts in timestamps.to_pydatetime():
        for sp in settlement_points:
            if spp.get((ts, sp)) is None or lam.get(ts) is None:
                complete[sp] = False
            else:
                out[sp] += float(spp[(ts, sp)]) - float(lam[ts])
    return {sp: out[sp] for sp in settlement_points if complete[sp]}


def _terms(contributions: pd.Series, shift_factors: pd.Series) -> list[AnalysisContributionTerm]:
    contributions = contributions[contributions != 0.0]
    ordered = contributions.reindex(contributions.abs().sort_values(ascending=False).index)
    return [AnalysisContributionTerm(constraint_key=str(key), contribution=float(value),
                                    shift_factor=float(shift_factors.loc[key]))
            for key, value in ordered.items()]


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


@router.get("/node", response_model=NodeAnalysisAvailableResponse | NodeAnalysisUnavailableResponse,
            summary="Full SF-column constraint attribution for a settlement point")
def get_node(
    settlement_point: str = Query(..., min_length=1),
    delivery_date: date = Query(...),
    basis: str = Query("predicted", pattern="^(predicted|realized)$"),
    run_id: str | None = Query(None),
    horizon: int | None = Query(None, ge=1, le=2),
    hours: list[datetime] | None = Query(None),
    min_abs_sf: float = Query(0.0, ge=0.0),
) -> NodeAnalysisAvailableResponse | NodeAnalysisUnavailableResponse:
    """Decompose a node from every represented constraint, never a brief top-k."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id = _resolve_run(cur, run_id)
        horizon = _resolve_horizon(cur, run_id, delivery_date, horizon)
        if horizon is None:
            return NodeAnalysisUnavailableResponse(
                available=False, unavailable_reason="artifact_missing", run_id=run_id,
                delivery_date=delivery_date,
            )
        artifact = load_daily_artifact(cur, run_id, delivery_date, horizon)
        if artifact is None:
            return NodeAnalysisUnavailableResponse(
                available=False, unavailable_reason="artifact_missing", run_id=run_id,
                delivery_date=delivery_date, horizon=horizon,
            )
        if settlement_point not in artifact.SF.columns:
            raise HTTPException(status_code=404, detail="settlement point is absent from this artifact.")
        selected = _selected_hours(artifact, hours)
        mu = (load_realized_mu(cur, selected, artifact.SF.index).reindex(artifact.SF.index).fillna(0.0)
              if basis == "realized"
              else artifact.E_mu.loc[selected].sum(axis=0))
        sf = artifact.SF[settlement_point]
        contributions = node_contributions(artifact, settlement_point, mu)
        contributions = contributions[sf.abs() >= min_abs_sf]
        total = float(contributions.sum())
        settled = _settled_congestion(cur, [settlement_point], selected).get(settlement_point)

    return NodeAnalysisAvailableResponse(
        available=True, settlement_point=settlement_point, run_id=run_id,
        delivery_date=delivery_date, horizon=horizon, basis=basis, hours=list(selected), total=total,
        n_terms=int((contributions != 0.0).sum()),
        coverage=None if settled in (None, 0.0) else total / settled,
        terms=_terms(contributions, sf),
    )


@router.get("/path", response_model=PathAnalysisAvailableResponse | PathAnalysisUnavailableResponse,
            summary="Full SF-pair constraint attribution for a settlement-point path")
def get_path(
    source: str = Query(..., min_length=1),
    sink: str = Query(..., min_length=1),
    delivery_date: date = Query(...),
    basis: str = Query("predicted", pattern="^(predicted|realized)$"),
    run_id: str | None = Query(None),
    horizon: int | None = Query(None, ge=1, le=2),
    hours: list[datetime] | None = Query(None),
    min_abs_sf: float = Query(0.0, ge=0.0),
) -> PathAnalysisAvailableResponse | PathAnalysisUnavailableResponse:
    """Decompose ``cong[sink] - cong[source]`` over the artifact's full SF pair."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id = _resolve_run(cur, run_id)
        horizon = _resolve_horizon(cur, run_id, delivery_date, horizon)
        if horizon is None:
            return PathAnalysisUnavailableResponse(
                available=False, unavailable_reason="artifact_missing", run_id=run_id,
                delivery_date=delivery_date,
            )
        artifact = load_daily_artifact(cur, run_id, delivery_date, horizon)
        if artifact is None:
            return PathAnalysisUnavailableResponse(
                available=False, unavailable_reason="artifact_missing", run_id=run_id,
                delivery_date=delivery_date, horizon=horizon,
            )
        unknown = [sp for sp in (source, sink) if sp not in artifact.SF.columns]
        if unknown:
            raise HTTPException(status_code=404, detail="settlement point is absent from this artifact.")
        selected = _selected_hours(artifact, hours)
        mu = (load_realized_mu(cur, selected, artifact.SF.index).reindex(artifact.SF.index).fillna(0.0)
              if basis == "realized"
              else artifact.E_mu.loc[selected].sum(axis=0))
        beta = artifact.SF[source] - artifact.SF[sink]
        contributions = pair_contributions(artifact.SF, mu, sink=sink, source=source)
        contributions = contributions[beta.abs() >= min_abs_sf]
        terms = _terms(contributions, beta)

    absolute = contributions.abs().sort_values(ascending=False)
    mass = float(absolute.sum())
    shares = absolute / mass if mass else absolute
    return PathAnalysisAvailableResponse(
        available=True, source=source, sink=sink, run_id=run_id, delivery_date=delivery_date,
        horizon=horizon, basis=basis, hours=list(selected), spread=float(contributions.sum()),
        n_terms=int((contributions != 0.0).sum()), terms=terms,
        composition=PathComposition(
            top_share=float(shares.iloc[0]) if len(shares) else 0.0,
            second_share=float(shares.iloc[1]) if len(shares) > 1 else 0.0,
            tail_share=float(shares.iloc[2:].sum()) if len(shares) > 2 else 0.0,
            n_terms=int((contributions != 0.0).sum()),
            top_constraint_key=None if not len(shares) else str(shares.index[0]),
            second_constraint_key=None if len(shares) < 2 else str(shares.index[1]),
        ),
    )


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
