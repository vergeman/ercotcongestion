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


# ---- /api/ercot_state_range ---------------------------------------------
#
# Per-hour ERCOT settlement-point congestion, read from the active run's
# congestion_matrices.npz. Mirrors StateRangeResponse in shape so the client
# can align its prefetch pipeline.

class ErcotSpState(BaseModel):
    sp_id: str
    congestion: float | None


class ErcotStateRangeEntry(BaseModel):
    interval_ts: datetime
    sps: list[ErcotSpState]


class ErcotStateRangeResponse(BaseModel):
    start: datetime
    end: datetime
    count: int
    entries: list[ErcotStateRangeEntry]


# ---- /api/ercot_spp_range -----------------------------------------------
#
# Raw DAM SPP (NP4-190-CD) per settlement point, per hour. Feeds the LMP
# palette's right pane so LMP-vs-LMP comparison uses ERCOT's own published
# prices, not a derived (SPP − system_λ) quantity. Read directly from the
# ``ercot_dam_spp`` table rather than the run's congestion matrix — the
# matrix stores only the shifted congestion component, not the raw price.

class ErcotSpSpp(BaseModel):
    sp_id: str
    spp: float | None


class ErcotSppRangeEntry(BaseModel):
    interval_ts: datetime
    sps: list[ErcotSpSpp]


class ErcotSppRangeResponse(BaseModel):
    start: datetime
    end: datetime
    count: int
    entries: list[ErcotSppRangeEntry]


# ---- /api/ibp/ercot ------------------------------------------------------
#
# Serves the promoted bp_ercot panel for a single hour. The run_id is
# resolved per-request from ``implied_binding_proximity_current[ercot]``
# so promotion flips take effect without a redeploy.

class IbpErcotPoint(BaseModel):
    settlement_point: str
    bp: float


class IbpErcotResponse(BaseModel):
    ts: datetime
    run_id: str
    points: list[IbpErcotPoint]


# ---- /api/ibp/ercot_range -----------------------------------------------
#
# Range sibling of /ibp/ercot. One round-trip per prefetch window; slots
# into the client's prefetchWindow fan-out alongside /ercot_state_range and
# /ercot_spp_range. Same 503 soft-fail contract as the other ERCOT-side
# range endpoints when nothing is promoted yet, so the client can render
# the model pane alone.

class IbpErcotRangeEntry(BaseModel):
    interval_ts: datetime
    points: list[IbpErcotPoint]


class IbpErcotRangeResponse(BaseModel):
    start: datetime
    end: datetime
    count: int
    run_id: str
    entries: list[IbpErcotRangeEntry]


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
    zone_rank_spearman_per_hour: float | None = Field(
        None,
        description=(
            "Mean over hours of per-hour spatial rank correlation across "
            "the derived-zone means; not comparable to the per-SP "
            "temporal Spearman in mapping_correlation_summary."
        ),
    )
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


# ---- /api/meta -----------------------------------------------------------

class MetaResponse(BaseModel):
    """What the API is currently serving. Read-only surface for debug UI.

    ``run_id``, ``ref``, ``algo``, ``k`` are derived from the served
    scorecard cell; ``promoted_at`` is the IBP DB pointer timestamp.
    Any field is ``None`` when the underlying artifact isn't in place —
    e.g. no cell has been promoted yet, or the DB pointer is unset.
    """
    run_id: str | None = None
    ref: str | None = None
    algo: str | None = None
    k: int | None = None
    promoted_at: datetime | None = None
