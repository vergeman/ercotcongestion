"""Build bounded causal Matrix frames from immutable SF artifacts."""

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Protocol

import pandas as pd
from fastapi import HTTPException

from compute.sf_map.model.fit import SF_ABS_CAP
from api.schemas.matrix import MatrixColumn, MatrixFrame, MatrixRow, MatrixSfValues
from api.services.constraint_keys import split_constraint_key
from api.services.sf_artifacts import delivery_date_for
from api.services.time import coerce_utc
from api.services.matrix.models import MatrixFrameRequest
from api.services.matrix.selection import (
    DEFAULT_ANCHORS,
    anchor_contribution_ranked,
    cursor_mu_abs,
    select_constraints_major,
    select_nodes_major,
)


class MatrixData(Protocol):
    def artifact_context(self, delivery_date): ...
    def realized_mu(self, interval_ts: datetime, constraint_keys) -> dict[str, float]: ...
    def constraint_types(self, keys: list[str]) -> dict[str, str]: ...


def _round(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def _unavailable(run_id: str, delivery_date, interval_ts: datetime, reason: str) -> MatrixFrame:
    return MatrixFrame(
        available=False, unavailable_reason=reason, run_id=run_id,
        delivery_date=delivery_date, interval_ts=interval_ts,
        sf=MatrixSfValues(row_count=0, column_count=0, values=[]),
    )


def build_frame(
    request: MatrixFrameRequest, repository: MatrixData,
    metadata: dict[str, tuple[str | None, str | None]],
) -> MatrixFrame:
    """Return the Matrix's stable, bounded wire rectangle for one cursor hour."""
    interval_ts = coerce_utc(request.interval_ts)
    delivery_date = delivery_date_for(interval_ts)
    context = repository.artifact_context(delivery_date)
    if context is None:
        raise HTTPException(status_code=503, detail="no forecast run is published yet.")
    if context.artifact is None:
        return _unavailable(context.run_id, delivery_date, interval_ts, "artifact_missing")
    artifact = context.artifact
    hour = pd.Timestamp(interval_ts)
    if hour not in artifact.E_mu.index:
        return _unavailable(context.run_id, delivery_date, interval_ts, "interval_not_in_artifact")

    exact_mu = artifact.E_mu.loc[hour]
    dam_by_key = repository.realized_mu(interval_ts, artifact.SF.index)
    contribution = (artifact.E_mu.abs().sum(axis=0) * artifact.SF.abs().sum(axis=1)).astype(float)
    contribution_ranked = [
        str(key) for key in sorted(artifact.SF.index, key=lambda key: (-contribution.loc[key], str(key)))
    ]
    if request.row_order == "anchor_contribution":
        ranked_rows = anchor_contribution_ranked(
            artifact, exact_mu, dam_by_key,
            [sp for sp in DEFAULT_ANCHORS if sp in artifact.SF.columns],
        )
    elif request.row_order == "cursor_mu":
        cursor = cursor_mu_abs(exact_mu, dam_by_key, artifact.SF.index)
        ranked_rows = sorted((str(key) for key in artifact.SF.index), key=lambda key: (-cursor[key], key))
    else:
        ranked_rows = contribution_ranked

    pinned_rows = [key for key in request.pinned_constraints if key in artifact.SF.index]
    pinned_columns = [key for key in request.pinned_settlement_points if key in artifact.SF.columns]
    if (peek := (request.peek_constraint or "").strip()) and peek in artifact.SF.index and peek not in pinned_rows:
        pinned_rows.append(peek)
    if (peek := (request.peek_settlement_point or "").strip()) and peek in artifact.SF.columns and peek not in pinned_columns:
        pinned_columns.append(peek)

    if request.orientation == "nodes":
        row_keys, column_keys, col_max, row_types = select_nodes_major(
            artifact, exact_mu, dam_by_key, pinned_rows, pinned_columns,
            request.settlement_point_search, request.row_limit, request.column_limit,
            repository.constraint_types,
        )
    else:
        row_keys, column_keys, col_max, row_types = select_constraints_major(
            artifact, ranked_rows, metadata, pinned_rows, pinned_columns,
            request.constraint_search, request.constraint_type,
            request.settlement_point_search, request.row_limit, request.column_limit,
            request.row_preset, request.column_set, repository.constraint_types,
        )

    daily_ranks = {key: rank for rank, key in enumerate(contribution_ranked, start=1)}
    rows = []
    matched_dam = 0
    for key in row_keys:
        name, contingency = split_constraint_key(str(key))
        dam_mu = dam_by_key.get(str(key))
        matched_dam += dam_mu is not None
        rows.append(MatrixRow(
            constraint_key=str(key), constraint_name=name, contingency_name=contingency,
            constraint_type=row_types.get(str(key)), forecast_mu=_round(float(exact_mu.loc[key])),
            ercot_dam_mu=dam_mu, daily_rank=daily_ranks[str(key)],
            binding_hours=int((artifact.E_mu[key].abs() > 0).sum()),
            max_abs_sf=_round(float(artifact.SF.loc[key].abs().max())),
        ))
    columns = [MatrixColumn(
        settlement_point=str(key), settlement_point_type=metadata.get(str(key), (None, None))[0],
        load_zone=metadata.get(str(key), (None, None))[1], max_abs_sf=_round(float(col_max.loc[key])),
    ) for key in column_keys]
    row_sf = artifact.SF.loc[row_keys]
    sf_day_max_abs = float(artifact.SF.abs().to_numpy().max()) if not artifact.SF.empty else 0.0
    contribution_day_max_abs = float((artifact.E_mu.abs().max(axis=0) * artifact.SF.abs().max(axis=1)).max()) if not artifact.SF.empty else 0.0
    return MatrixFrame(
        available=True, run_id=context.run_id, delivery_date=delivery_date, interval_ts=interval_ts,
        dam_status="available" if matched_dam == len(rows) else ("partial" if matched_dam else "pending"),
        rows=rows, columns=columns, rows_truncated=len(row_keys) < len(artifact.SF.index),
        columns_truncated=len(column_keys) < len(artifact.SF.columns),
        total_constraint_count=len(contribution_ranked), total_settlement_point_count=len(artifact.SF.columns),
        sf_day_max_abs=sf_day_max_abs, contribution_day_max_abs=contribution_day_max_abs,
        sf_abs_cap=SF_ABS_CAP, orientation=request.orientation,
        sf=MatrixSfValues(
            row_count=len(rows), column_count=len(columns),
            values=[_round(float(value)) for value in row_sf.loc[row_keys, column_keys].to_numpy().ravel()],
        ),
    )
