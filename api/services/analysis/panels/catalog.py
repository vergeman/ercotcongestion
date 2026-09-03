"""Catalog endpoints: the full per-day universe of nodes, settlement points,
constraints, and ESSP groups — search/discovery surfaces, never a Brief top-k."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from fastapi import Depends, HTTPException, Query
import pandas as pd
from psycopg.rows import dict_row

from api.db import get_pool
from api.dependencies import server_selected_run as _server_selected_run
from api.schemas.analysis import (
    AnalysisContributionTerm,
    NodeAnalysisAvailableResponse,
    NodeAnalysisUnavailableResponse,
    AnalysisSettlementPointsAvailableResponse,
    AnalysisConstraintsAvailableResponse,
    AnalysisEsspGroupsAvailableResponse,
    AnalysisEsspGroupsUnavailableResponse,
)
from compute.analysis.metadata import load_sp_metadata
from api.services.sf_artifacts import load_daily_artifact
from api.services.analysis.repositories.market import (
    essp_member_count as _essp_member_count,
    node_market_state as _node_market_state,
    settled_congestion as _settled_congestion,
)
from api.services.analysis.resolution import selected_hours as _selected_hours
from api.services.analysis.queries import (
    constraints_response,
    essp_groups_response,
    node_response,
    settlement_points_response,
)
from api.services.analysis.panels._common import _resolve_or_unavailable


def _constraint_geo(cur, keys: list[str]) -> dict[str, dict]:
    """Best-effort ctype/zone/kv_max per key; absent geography is null, never
    an error.

    """
    if not keys:
        return {}
    cur.execute(
        "SELECT DISTINCT ON (constraint_key) constraint_key, ctype, zone_shares, kv_max "
        "FROM constraint_geo WHERE constraint_key = ANY(%s) "
        "ORDER BY constraint_key, window_start DESC",
        (keys,),
    )
    result: dict[str, dict] = {}
    for row in cur.fetchall():
        shares = row["zone_shares"] or {}
        result[str(row["constraint_key"])] = {
            "ctype": row["ctype"],
            "zone": max(shares, key=shares.get) if shares else None,
            "kv_max": row["kv_max"],
        }
    return result


def _terms(
    contributions: pd.Series, shift_factors: pd.Series
) -> list[AnalysisContributionTerm]:
    contributions = contributions[contributions != 0.0]
    ordered = contributions.reindex(
        contributions.abs().sort_values(ascending=False).index
    )
    return [
        AnalysisContributionTerm(
            constraint_key=str(key),
            contribution=float(value),
            shift_factor=float(shift_factors.loc[key]),
        )
        for key, value in ordered.items()
    ]


def _structural_terms(
    shift_factors: pd.Series, contributions: pd.Series
) -> list[AnalysisContributionTerm]:
    """Every nonzero SF relationship, including constraints quiet this hour."""
    sf = shift_factors[shift_factors != 0.0]
    ordered = sf.reindex(sf.abs().sort_values(ascending=False).index)
    return [
        AnalysisContributionTerm(
            constraint_key=str(key),
            contribution=float(contributions.loc[key]),
            shift_factor=float(value),
        )
        for key, value in ordered.items()
    ]


def get_node(
    settlement_point: str = Query(..., min_length=1),
    delivery_date: date = Query(...),
    basis: str = Query("predicted", pattern="^(predicted|realized)$"),
    run_id: str | None = Depends(_server_selected_run),
    horizon: int | None = Query(None, ge=1, le=2),
    hours: list[datetime] | None = Query(None),
    min_abs_sf: float = Query(0.0, ge=0.0),
    mode: Literal["drivers", "structural"] = Query("drivers"),
    include_detail: bool = Query(
        False, description="Include Matrix Detail's structural terms and ESSP count."
    ),
) -> NodeAnalysisAvailableResponse | NodeAnalysisUnavailableResponse:
    """Decompose a node from every represented constraint, never a brief top-k."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, horizon, unavailable = _resolve_or_unavailable(
            cur, run_id, delivery_date, horizon
        )
        if unavailable is not None:
            return unavailable
        artifact = load_daily_artifact(cur, run_id, delivery_date, horizon)
        if artifact is None:
            return NodeAnalysisUnavailableResponse(
                available=False,
                unavailable_reason="artifact_missing",
                run_id=run_id,
                delivery_date=delivery_date,
                horizon=horizon,
            )
        return node_response(
            cur=cur,
            artifact=artifact,
            settlement_point=settlement_point,
            run_id=run_id,
            delivery_date=delivery_date,
            horizon=horizon,
            basis=basis,
            hours=hours,
            min_abs_sf=min_abs_sf,
            mode=mode,
            include_detail=include_detail,
            selected_hours=_selected_hours,
            settled_congestion=_settled_congestion,
            node_market_state=_node_market_state,
            essp_member_count=_essp_member_count,
            terms=_terms,
            structural_terms=_structural_terms,
        )


def get_settlement_points(
    delivery_date: date = Query(...),
    run_id: str | None = Depends(_server_selected_run),
    horizon: int | None = Query(None, ge=1, le=2),
) -> (
    AnalysisSettlementPointsAvailableResponse
    | NodeAnalysisUnavailableResponse
):
    """List all artifact columns once for counterparty discovery, never a Matrix screen."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, horizon, unavailable = _resolve_or_unavailable(
            cur, run_id, delivery_date, horizon
        )
        if unavailable is not None:
            return unavailable
        artifact = load_daily_artifact(cur, run_id, delivery_date, horizon)
        if artifact is None:
            return NodeAnalysisUnavailableResponse(
                available=False,
                unavailable_reason="artifact_missing",
                run_id=run_id,
                delivery_date=delivery_date,
                horizon=horizon,
            )
    return settlement_points_response(
        artifact=artifact,
        run_id=run_id,
        delivery_date=delivery_date,
        horizon=horizon,
        metadata_loader=load_sp_metadata,
    )


def get_constraints(
    delivery_date: date = Query(...),
    run_id: str | None = Depends(_server_selected_run),
    horizon: int | None = Query(None, ge=1, le=2),
) -> AnalysisConstraintsAvailableResponse | NodeAnalysisUnavailableResponse:
    """List every constraint in one day's artifact for search, ranked by
    Σ|E_mu| — the full universe, never a Brief top-k."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, horizon, unavailable = _resolve_or_unavailable(
            cur, run_id, delivery_date, horizon
        )
        if unavailable is not None:
            return unavailable
        artifact = load_daily_artifact(cur, run_id, delivery_date, horizon)
        if artifact is None:
            return NodeAnalysisUnavailableResponse(
                available=False,
                unavailable_reason="artifact_missing",
                run_id=run_id,
                delivery_date=delivery_date,
                horizon=horizon,
            )
        keys = [str(key) for key in artifact.E_mu.columns]
        geography = _constraint_geo(cur, keys)

    return constraints_response(
        artifact=artifact,
        geography=geography,
        run_id=run_id,
        delivery_date=delivery_date,
        horizon=horizon,
    )


def get_essp_groups(
    interval_ts: datetime = Query(...),
    source: str = Query("study", pattern="^(study|final)$"),
) -> AnalysisEsspGroupsAvailableResponse | AnalysisEsspGroupsUnavailableResponse:
    """Return raw ESSP membership for one hour and vintage.

    """
    if interval_ts.tzinfo is None:
        raise HTTPException(
            status_code=422, detail="interval_ts must include a UTC offset."
        )
    interval_ts = pd.Timestamp(interval_ts).tz_convert("UTC").to_pydatetime()
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT group_index, array_agg(settlement_point ORDER BY settlement_point) AS settlement_points "
            "FROM ercot_essp WHERE interval_ts = %s AND is_study = %s "
            "GROUP BY group_index ORDER BY group_index",
            (interval_ts, source == "study"),
        )
        rows = cur.fetchall()
    return essp_groups_response(rows=rows, interval_ts=interval_ts, source=source)
