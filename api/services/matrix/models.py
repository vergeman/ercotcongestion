"""Input values for the Matrix frame service."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class MatrixFrameRequest:
    interval_ts: datetime
    row_limit: int
    column_limit: int
    row_preset: str
    constraint_type: str | None
    constraint_search: str | None
    settlement_point_search: str | None
    pinned_constraints: list[str]
    pinned_settlement_points: list[str]
    peek_constraint: str | None
    peek_settlement_point: str | None
    column_set: str
    orientation: str
    row_order: str
