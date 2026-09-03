"""Grade endpoints: the day's constraint/node scorecard and its 30-day history.

The two halves stay separate — constraints and nodes are scored and served
independently, never blended into one number."""

from __future__ import annotations

from datetime import date

from fastapi import Depends, Query
from psycopg.rows import dict_row

from api.db import get_pool
from api.dependencies import server_selected_run as _server_selected_run
from api.schemas.analysis import (
    GradeAvailableResponse,
    GradeHalfResponse,
    NodeAnalysisUnavailableResponse,
    GradeHistoryHalfResponse,
    GradeHistoryDayResponse,
    GradeHistoryAvailableResponse,
)
from compute.analysis import brief_grade
from api.services.analysis.panels._common import _resolve_or_unavailable


def get_grade(
    delivery_date: date = Query(...),
    run_id: str | None = Depends(_server_selected_run),
    horizon: int | None = Query(None, ge=1, le=2),
) -> GradeAvailableResponse | NodeAnalysisUnavailableResponse:
    """Score constraints without blending them with the separately exposed node half."""
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, horizon, unavailable = _resolve_or_unavailable(
            cur, run_id, delivery_date, horizon
        )
        if unavailable is not None:
            return unavailable
        # An unsettled delivery day has no DAM μ to grade against.  Report both
        # halves as settlement-pending rather than a real-looking zero score:
        # the grade scorer would otherwise return magnitude_overlap 0.0 with
        # null APs, and a materialization run before DAM lands would persist it.
        if brief_grade.settled_mu_profile(cur, delivery_date).empty:
            pending = GradeHalfResponse(
                graded=False, unavailable_reason="settlement_pending"
            )
            return GradeAvailableResponse(
                available=True,
                run_id=run_id,
                delivery_date=delivery_date,
                horizon=horizon,
                constraints=pending,
                nodes=pending,
            )
        cur.execute(
            "SELECT subject, detail FROM analysis_grade_daily "
            "WHERE run_id = %s AND delivery_date = %s AND horizon = %s AND detail IS NOT NULL",
            (run_id, delivery_date, horizon),
        )
        materialized = {str(row["subject"]): row["detail"] for row in cur.fetchall()}
        if "constraints" in materialized and "nodes" in materialized:
            return GradeAvailableResponse(
                available=True,
                run_id=run_id,
                delivery_date=delivery_date,
                horizon=horizon,
                constraints=GradeHalfResponse(
                    **_brief_payload(materialized["constraints"])
                ),
                nodes=GradeHalfResponse(**_brief_payload(materialized["nodes"])),
            )
        constraints = brief_grade.grade_constraint_profiles(
            cur, run_id, delivery_date, horizon
        )
        nodes = brief_grade.grade_node_profiles(cur, run_id, delivery_date, horizon)
    if constraints is None:
        return NodeAnalysisUnavailableResponse(
            available=False,
            unavailable_reason="artifact_missing",
            run_id=run_id,
            delivery_date=delivery_date,
            horizon=horizon,
        )
    return GradeAvailableResponse(
        available=True,
        run_id=run_id,
        delivery_date=delivery_date,
        horizon=horizon,
        constraints=GradeHalfResponse(
            **_brief_payload(brief_grade.serialize_grade_half(constraints))
        ),
        nodes=(
            _brief_payload(brief_grade.serialize_grade_half(nodes))
            if nodes is not None
            else GradeHalfResponse(graded=False, unavailable_reason="node_data_missing")
        ),
    )


def _brief_payload(payload: dict) -> dict:
    """Use current Brief source definitions for serialized source IDs."""
    result = dict(payload)
    source_ids = {source["id"] for source in result.get("source_metrics", [])}
    result["sources"] = [
        {"id": source.id, "label": source.label, "definition": source.definition}
        for source in brief_grade.SOURCE_DEFINITIONS
        if source.id in source_ids
    ]
    return result


def get_grade_history(
    delivery_date: date = Query(...),
    run_id: str | None = Depends(_server_selected_run),
    horizon: int | None = Query(None, ge=1, le=2),
    days: int = Query(30, ge=1, le=30),
) -> GradeHistoryAvailableResponse | NodeAnalysisUnavailableResponse:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, horizon, unavailable = _resolve_or_unavailable(
            cur, run_id, delivery_date, horizon
        )
        if unavailable is not None:
            return unavailable
        cur.execute(
            "SELECT delivery_date, subject, model, persistence FROM analysis_grade_daily "
            "WHERE run_id = %s AND horizon = %s AND delivery_date >= %s - %s "
            "AND delivery_date < %s ORDER BY delivery_date, subject",
            (run_id, horizon, delivery_date, days, delivery_date),
        )
        grouped: dict[date, dict[str, dict]] = {}
        for row in cur.fetchall():
            grouped.setdefault(row["delivery_date"], {})[str(row["subject"])] = {
                "model": row["model"],
                "persistence": row["persistence"],
            }
    descriptors = [
        {"id": source.id, "label": source.label, "definition": source.definition}
        for source in brief_grade.SOURCE_DEFINITIONS
    ]
    result = [
        GradeHistoryDayResponse(
            delivery_date=day,
            constraints=GradeHistoryHalfResponse(
                **values["constraints"],
                sources=descriptors,
                source_metrics=[
                    {
                        "id": brief_grade.SOURCE_DEFINITIONS[0].id,
                        "metrics": values["constraints"]["model"],
                    },
                    {
                        "id": brief_grade.SOURCE_DEFINITIONS[1].id,
                        "metrics": values["constraints"]["persistence"],
                    },
                ],
            ),
            nodes=GradeHistoryHalfResponse(
                **values["nodes"],
                sources=descriptors,
                source_metrics=[
                    {
                        "id": brief_grade.SOURCE_DEFINITIONS[0].id,
                        "metrics": values["nodes"]["model"],
                    },
                    {
                        "id": brief_grade.SOURCE_DEFINITIONS[1].id,
                        "metrics": values["nodes"]["persistence"],
                    },
                ],
            ),
        )
        for day, values in grouped.items()
        if "constraints" in values and "nodes" in values
    ]
    return GradeHistoryAvailableResponse(
        available=True,
        run_id=run_id,
        delivery_date=delivery_date,
        horizon=horizon,
        days=result,
    )
