"""Artifact-backed Analysis response assembly."""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException

from compute.analysis.metadata import load_sp_metadata
from compute.projection.codecs import node_contributions
from api.services.constraint_keys import split_constraint_key
from api.services.sf_artifacts import load_realized_mu
from api.schemas.analysis import (
    AnalysisConstraintRow,
    AnalysisConstraintsAvailableResponse,
    AnalysisSettlementPointMetadata,
    AnalysisSettlementPointsAvailableResponse,
    AnalysisEsspGroupsAvailableResponse,
    AnalysisEsspGroupsUnavailableResponse,
    EsspGroup,
    NodeAnalysisAvailableResponse,
)


def essp_groups_response(*, rows: list[dict], interval_ts, source: str):
    if not rows:
        return AnalysisEsspGroupsUnavailableResponse(
            available=False, unavailable_reason="essp_missing", interval_ts=interval_ts, source=source,
        )
    return AnalysisEsspGroupsAvailableResponse(
        available=True, interval_ts=interval_ts, source=source,
        groups=[EsspGroup(group_index=int(row["group_index"]),
                          settlement_points=list(row["settlement_points"])) for row in rows],
    )


def settlement_points_response(*, artifact, run_id: str, delivery_date, horizon: int,
                               metadata_loader=load_sp_metadata):
    settlement_points = sorted(str(sp) for sp in artifact.SF.columns)
    metadata = metadata_loader(settlement_points)
    return AnalysisSettlementPointsAvailableResponse(
        available=True, run_id=run_id, delivery_date=delivery_date, horizon=horizon,
        settlement_points=settlement_points,
        metadata=[
            AnalysisSettlementPointMetadata(
                settlement_point=point,
                settlement_point_type=metadata[point].get("sp_type"),
                load_zone=metadata[point].get("load_zone"),
                lat=metadata[point].get("lat"),
                lon=metadata[point].get("lon"),
            )
            for point in settlement_points
        ],
    )


def constraints_response(*, artifact, geography: dict[str, dict], run_id: str,
                         delivery_date, horizon: int):
    mu_mass = artifact.E_mu.abs().sum(axis=0)
    ranked = mu_mass.sort_values(ascending=False, kind="stable")
    binding_hours = artifact.E_mu.ne(0.0).sum(axis=0)
    rows = []
    for rank, raw_key in enumerate(ranked.index, start=1):
        key = str(raw_key)
        name, contingency = split_constraint_key(key)
        geo = geography.get(key, {})
        rows.append(AnalysisConstraintRow(
            constraint_key=key, name=name, contingency=contingency,
            ctype=geo.get("ctype"), zone=geo.get("zone"), kv_max=geo.get("kv_max"),
            binding_hours=int(binding_hours.loc[key]), daily_mu_rank=rank,
            daily_mu_sum=float(mu_mass.loc[key]),
        ))
    return AnalysisConstraintsAvailableResponse(
        available=True, run_id=run_id, delivery_date=delivery_date, horizon=horizon,
        rows=rows, n_total=len(rows),
    )


def node_response(*, cur, artifact, settlement_point: str, run_id: str, delivery_date,
                  horizon: int, basis: str, hours: list[datetime] | None, min_abs_sf: float,
                  mode: str, include_detail: bool, selected_hours, settled_congestion,
                  node_market_state, essp_member_count, terms, structural_terms):
    if settlement_point not in artifact.SF.columns:
        raise HTTPException(status_code=404, detail="settlement point is absent from this artifact.")
    selected = selected_hours(artifact, hours)
    mu = (load_realized_mu(cur, selected, artifact.SF.index).reindex(artifact.SF.index).fillna(0.0)
          if basis == "realized" else artifact.E_mu.loc[selected].sum(axis=0))
    sf = artifact.SF[settlement_point]
    contributions = node_contributions(artifact, settlement_point, mu)
    contributions = contributions[sf.abs() >= min_abs_sf]
    total = float(contributions.sum())
    settled = settled_congestion(cur, [settlement_point], selected).get(settlement_point)
    market_state = node_market_state(cur, settlement_point, run_id, delivery_date, horizon,
                                     selected[0].to_pydatetime()) if len(selected) == 1 else None
    structural_sf = sf[sf.abs() >= min_abs_sf] if include_detail else None
    member_count = (essp_member_count(cur, settlement_point, selected[0].to_pydatetime())
                    if include_detail and len(selected) == 1 else None)
    return NodeAnalysisAvailableResponse(
        available=True, settlement_point=settlement_point, run_id=run_id,
        delivery_date=delivery_date, horizon=horizon, basis=basis, hours=list(selected), total=total,
        n_terms=(int(((sf.abs() >= min_abs_sf) & (sf != 0.0)).sum())
                 if mode == "structural" else int((contributions != 0.0).sum())),
        coverage=None if settled in (None, 0.0) else total / settled,
        terms=(structural_terms(sf[sf.abs() >= min_abs_sf], contributions)
               if mode == "structural" else terms(contributions, sf)),
        market_state=market_state,
        structural_n_terms=None if structural_sf is None else int((structural_sf != 0.0).sum()),
        structural_terms=(None if structural_sf is None else structural_terms(structural_sf, contributions)),
        essp_member_count=member_count,
    )
