"""Response schemas for the API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---- /api/state ----------------------------------------------------------

class BusState(BaseModel):
    bus_id: str
    fragility: float | None
    lmp: float | None
    basis: float | None = None

class BindingLine(BaseModel):
    line: str
    shadow_price: float


class Contingency(BaseModel):
    line: str
    stress: float


class SnapshotMeta(BaseModel):
    interval_ts: datetime
    status: str
    objective_cost: float | None = None
    total_load_mw: float | None = None
    total_gen_mw: float | None = None
    n_binding_lines: int | None = None
    lmp_min: float | None = None
    lmp_mean: float | None = None
    lmp_max: float | None = None
    fragility_total: float | None = None
    fragility_top10_share: float | None = None
    binding_lines: list[BindingLine] = Field(default_factory=list)
    top_contingencies: list[Contingency] = Field(default_factory=list)
    dispatch_by_carrier: dict[str, float] = Field(default_factory=dict)
    wind_factor_by_region: dict[str, float] = Field(default_factory=dict)
    solar_factor_by_region: dict[str, float] = Field(default_factory=dict)
    outage_posting_ts: datetime | None = None
    error_message: str | None = None


class StateResponse(BaseModel):
    interval_ts: datetime
    meta: SnapshotMeta
    buses: list[BusState]


# ---- /api/state_range ----------------------------------------------------

class StateRangeEntry(BaseModel):
    interval_ts: datetime
    meta: SnapshotMeta
    buses: list[BusState]


class StateRangeResponse(BaseModel):
    start: datetime
    end: datetime
    count: int
    entries: list[StateRangeEntry]


# ---- /api/validation -----------------------------------------------------

class CorrelationResult(BaseModel):
    n: int
    rho: float | None  # None if degenerate (e.g. zero variance, n<2)


class ValidationResponse(BaseModel):
    start: datetime
    end: datetime
    n_snapshots: int
    n_observations: int
    overall: CorrelationResult
    congested: CorrelationResult
    quiet: CorrelationResult
    congested_threshold_n_binding: int = Field(
        ..., description="Snapshots with n_binding_lines >= this count classified as congested",
    )
    warnings: list[str] = Field(default_factory=list)


# ---- /api/topology -------------------------------------------------------

class TopologyResponse(BaseModel):
    """Loose schema — actual payload is GeoJSON-shaped FeatureCollections."""
    buses: dict[str, Any]
    lines: dict[str, Any]
    zones: dict[str, Any] | None = None
