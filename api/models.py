"""Response schemas for the API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---- /api/state ----------------------------------------------------------

class BusState(BaseModel):
    bus_id: str
    modeled_congestion: float | None
    binding_proximity: float | None = None
    lmp: float | None
    basis: float | None = None

class BindingLine(BaseModel):
    line: str
    shadow_price: float


class Contingency(BaseModel):
    line: str
    stress: float


class ZoneOutage(BaseModel):
    """Per-load-zone outage MW from ERCOT outages_zonal."""
    thermal_mw: float
    irr_mw: float


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
    modeled_congestion_total: float | None = None
    modeled_congestion_abs_total: float | None = None
    modeled_congestion_top10_share: float | None = None
    binding_proximity_max: float | None = None
    binding_proximity_p95: float | None = None
    binding_lines: list[BindingLine] = Field(default_factory=list)
    top_contingencies: list[Contingency] = Field(default_factory=list)
    dispatch_by_carrier: dict[str, float] = Field(default_factory=dict)
    wind_factor_by_region: dict[str, float] = Field(default_factory=dict)
    solar_factor_by_region: dict[str, float] = Field(default_factory=dict)
    outage_posting_ts: datetime | None = None
    outages_by_zone: dict[str, ZoneOutage] | None = None
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


# ---- /api/validation (zone-aggregated scorecard) -------------------------

class ScorecardZone(BaseModel):
    cluster_id: int
    n_buses: int
    n_sps: int
    corr: float | None = Field(
        None,
        description="Pearson ρ between model_Z(t) and ercot_Z(t) over the window.",
    )
    sign_agreement: float | None = Field(
        None,
        description="Fraction of hours where sign(model_Z)==sign(ercot_Z), "
                    "excluding hours where either side falls within ±deadband $/MWh.",
    )
    model_side_std: float | None = Field(
        None,
        description="Std of per-bus corr(bus, ercot_Z) inside the zone.",
    )
    ercot_side_std: float | None = Field(
        None,
        description="Std of per-SP corr(sp, ercot_Z) inside the zone.",
    )
    outlier_buses: list[str] = Field(default_factory=list)
    outlier_sps: list[str] = Field(default_factory=list)


class ScorecardHeadline(BaseModel):
    rank_spearman: float | None
    mean_corr: float | None
    mean_sign_agreement: float | None
    n_hours: int
    n_zones: int


class ScorecardSeries(BaseModel):
    hours: list[str]
    cluster_ids: list[int]
    model_Z: list[list[float]] = Field(..., description="(n_hours, n_zones) model-side mean congestion.")
    ercot_Z: list[list[float]] = Field(..., description="(n_hours, n_zones) ERCOT-side mean congestion.")


class ScorecardParams(BaseModel):
    ref: str
    algo: str
    k: int
    deadband: float
    min_members: int


class ScorecardResponse(BaseModel):
    run_id: str
    params: ScorecardParams
    headline: ScorecardHeadline
    zones: list[ScorecardZone]
    series: ScorecardSeries
    warnings: list[str] = Field(default_factory=list)


# ---- /api/topology -------------------------------------------------------

class TopologyResponse(BaseModel):
    """Loose schema — actual payload is GeoJSON-shaped FeatureCollections."""
    buses: dict[str, Any]
    lines: dict[str, Any]
    zones: dict[str, Any] | None = None
