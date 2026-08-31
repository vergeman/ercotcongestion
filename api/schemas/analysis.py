"""Schemas served by the daily analysis and Brief routes."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from api.schemas.common import SourceDescriptor


# ---- /analysis/hero ------------------------------------------------------

class HeroSegment(BaseModel):
    """One rendered phrase and the slot whose raw values explain it."""
    text: str
    ref: str


class HeroSegments(BaseModel):
    headline: list[HeroSegment]
    lede: list[HeroSegment]


class HeroCursor(BaseModel):
    ws: str
    we: str
    t: str


class HeroProvenance(BaseModel):
    run_id: str
    delivery_date: date
    horizon: int
    basis: Literal["forecast", "settled"]


class HeroAvailableResponse(BaseModel):
    """On-demand hero and its evidence-bearing classified slots."""
    available: Literal[True]
    segments: HeroSegments
    # Slot keys and their numeric evidence are deliberately extensible while the
    # individual panel contracts are still being sequenced in 0003–0007.
    slots: dict[str, dict[str, Any]]
    verdict: dict[str, dict[str, Any] | None] | None
    cursor: HeroCursor
    provenance: HeroProvenance


class HeroUnavailableResponse(BaseModel):
    """Soft failure before a concrete artifact horizon can be resolved."""
    model_config = ConfigDict(extra="forbid")
    available: Literal[False]
    unavailable_reason: Literal["artifact_missing"]
    run_id: str
    delivery_date: date


class HeroUnavailableAtHorizonResponse(HeroUnavailableResponse):
    """Soft failure for a requested or resolved artifact horizon."""
    horizon: int


class HeroLatestResponse(BaseModel):
    """Newest delivery day whose v6 Brief tables can stitch their CT window."""
    available: bool
    run_id: str
    delivery_date: date | None = None
    horizon: int | None = None


# ---- /analysis/node ------------------------------------------------------

class AnalysisContributionTerm(BaseModel):
    constraint_key: str
    contribution: float
    shift_factor: float


class NodeMarketState(BaseModel):
    """Cursor-hour forecast and DAM values for one Matrix node Detail view."""
    forecast_congestion: float | None = None
    forecast_lmp: float | None = None
    realized_congestion: float | None = None
    forecast_error: float | None = None
    dam_lmp: float | None = None
    forecast_lambda_source: Literal["settled", "persisted"] | None = None


class NodeAnalysisAvailableResponse(BaseModel):
    available: Literal[True]
    settlement_point: str
    run_id: str
    delivery_date: date
    horizon: int
    basis: Literal["predicted", "realized"]
    hours: list[datetime]
    total: float
    n_terms: int
    coverage: float | None
    terms: list[AnalysisContributionTerm]
    market_state: NodeMarketState | None = None
    structural_n_terms: int | None = None
    structural_terms: list[AnalysisContributionTerm] | None = None
    essp_member_count: int | None = None


class NodeAnalysisUnavailableResponse(BaseModel):
    available: Literal[False]
    unavailable_reason: Literal["artifact_missing"]
    run_id: str
    delivery_date: date
    horizon: int | None = None


class AnalysisSettlementPointMetadata(BaseModel):
    """Static display metadata for one artifact settlement point."""
    settlement_point: str
    settlement_point_type: str | None = None
    load_zone: str | None = None
    lat: float | None = None
    lon: float | None = None


class AnalysisSettlementPointsAvailableResponse(BaseModel):
    """The exact settlement-point vocabulary represented by one day artifact."""
    available: Literal[True]
    run_id: str
    delivery_date: date
    horizon: int
    settlement_points: list[str]
    metadata: list[AnalysisSettlementPointMetadata]


class AnalysisSettlementPointsUnavailableResponse(NodeAnalysisUnavailableResponse):
    pass


# ---- /analysis/constraints ------------------------------------------------

class AnalysisConstraintRow(BaseModel):
    """One constraint's identity, best-effort geography, and this day's
    Σ|E_mu| rank — the full search index, never a Brief top-k."""
    constraint_key: str
    name: str
    contingency: str | None
    ctype: str | None = None
    zone: str | None = None
    kv_max: float | None = None
    binding_hours: int
    daily_mu_rank: int
    daily_mu_sum: float


class AnalysisConstraintsAvailableResponse(BaseModel):
    """The exact constraint vocabulary represented by one day's artifact."""
    available: Literal[True]
    run_id: str
    delivery_date: date
    horizon: int
    rows: list[AnalysisConstraintRow]
    n_total: int


class AnalysisConstraintsUnavailableResponse(NodeAnalysisUnavailableResponse):
    pass


# ---- /analysis/essp ------------------------------------------------------

class EsspGroup(BaseModel):
    """One ERCOT electrically-similar settlement-point group for one hour."""
    group_index: int
    settlement_points: list[str]


class AnalysisEsspGroupsAvailableResponse(BaseModel):
    """Hourly ESSP membership from one explicitly selected ERCOT vintage."""
    available: Literal[True]
    interval_ts: datetime
    source: Literal["study", "final"]
    groups: list[EsspGroup]


class AnalysisEsspGroupsUnavailableResponse(BaseModel):
    """Soft failure: the requested vintage has not been ingested for this hour."""
    available: Literal[False]
    unavailable_reason: Literal["essp_missing"]
    interval_ts: datetime
    source: Literal["study", "final"]


# ---- /analysis/forecast-mu -----------------------------------------------

class ForecastMuRow(BaseModel):
    """One requested constraint's hourly forecast-μ vector.

    A returned zero is evidence that the fit priced the constraint near zero.
    A missing requested key is reported separately because it was not in the
    artifact vocabulary at all.
    """
    constraint_key: str
    mu: list[float]
    total: float


class ForecastMuAvailableResponse(BaseModel):
    available: Literal[True]
    run_id: str
    delivery_date: date
    horizon: int
    hours: list[datetime]
    n_fit_constraints: int
    rows: list[ForecastMuRow]
    missing_constraint_keys: list[str]


class ForecastMuUnavailableResponse(NodeAnalysisUnavailableResponse):
    pass


# ---- /analysis/top-constraints ------------------------------------------

class TopConstraintRow(BaseModel):
    """One forecast/settled-union constraint row, ordered by the active phase."""
    constraint_key: str
    forecast_rank: int | None = None
    forecast_total: float
    forecast_peak: float
    forecast_hours: int
    zone: str | None = None
    kv_max: float | None = None
    settled_rank: int | None = None
    settled_total: float | None = None
    settled_peak: float | None = None
    settled_hours: int | None = None
    settled_history_p10: float | None = None
    settled_history_p25: float | None = None
    settled_history_p50: float | None = None
    settled_history_p75: float | None = None
    settled_history_p90: float | None = None
    settled_history: list[float] = []


class TopConstraintsAvailableResponse(BaseModel):
    available: Literal[True]
    run_id: str
    delivery_date: date
    horizon: int
    rows: list[TopConstraintRow]
    n_ranked: int
    k: int  # served forecast top-k; the client marks rows outside it after settlement.


class TopConstraintsUnavailableResponse(NodeAnalysisUnavailableResponse):
    pass


# ---- /analysis/context ---------------------------------------------------

class VoltageClassRow(BaseModel):
    voltage_class: str
    constraint_keys: int
    binding_hours: int
    average_mu: float
    share_of_mu: float


class ChronicElementRow(BaseModel):
    element: str
    contingency: str
    days_bound: int
    window_days: int = 30
    usual_total: float


class ContextAvailableResponse(BaseModel):
    available: Literal[True]
    run_id: str
    delivery_date: date
    horizon: int
    basis: Literal["forecast", "settled"]
    voltage_classes: list[VoltageClassRow]
    chronic_elements: list[ChronicElementRow]


class ContextUnavailableResponse(NodeAnalysisUnavailableResponse):
    pass


# ---- /analysis/standouts -------------------------------------------------

class StandoutRow(BaseModel):
    """One server-selected constraint compared with its own forecast history."""
    constraint_key: str
    kind: Literal["forecast_elevated", "chronic_under_called", "settled_elevated"]
    forecast_total: float
    forecast_history_median: float
    forecast_history_days: int
    chronic_bound_days: int | None = None
    settled_total: float | None = None
    zone: str | None = None
    kv_max: float | None = None
    forecast_rank: int | None = None
    forecast_peak: float | None = None
    forecast_hours: int | None = None
    settled_rank: int | None = None
    settled_peak: float | None = None
    settled_hours: int | None = None
    settled_history_p10: float | None = None
    settled_history_p25: float | None = None
    settled_history_p50: float | None = None
    settled_history_p75: float | None = None
    settled_history_p90: float | None = None
    settled_history: list[float] = []


class NodeStandoutRow(BaseModel):
    """One anomaly-selected node compared with its own forecast history."""
    settlement_point: str
    essp_member_count: int = 1
    kind: Literal["forecast_elevated", "forecast_depressed", "settled_elevated"]
    zone: str | None = None
    forecast_total: float
    forecast_rank: int | None = None
    forecast_history_median: float
    forecast_history_days: int
    settled_total: float | None = None
    settled_rank: int | None = None
    dominant_driver: str | None = None
    driver_share: float | None = None
    settled_history_p10: float | None = None
    settled_history_p25: float | None = None
    settled_history_p50: float | None = None
    settled_history_p75: float | None = None
    settled_history_p90: float | None = None
    settled_history: list[float] = []


class StandoutsAvailableResponse(BaseModel):
    available: Literal[True]
    run_id: str
    delivery_date: date
    horizon: int
    basis: Literal["forecast", "settled"]
    rows: list[StandoutRow]
    node_rows: list[NodeStandoutRow]


class StandoutsUnavailableResponse(NodeAnalysisUnavailableResponse):
    pass


# ---- /analysis/top-nodes -------------------------------------------------

class TopNodeRow(BaseModel):
    """One forecast/settled-union nodal row with full-column attribution."""
    settlement_point: str
    essp_member_count: int = 1
    zone: str | None = None
    forecast_rank: int | None = None
    forecast_total: float
    settled_rank: int | None = None
    settled_total: float | None = None
    delta: float | None = None
    dominant_driver: str | None = None
    driver_share: float | None = None
    coverage: float | None = None
    settled_history_p10: float | None = None
    settled_history_p25: float | None = None
    settled_history_p50: float | None = None
    settled_history_p75: float | None = None
    settled_history_p90: float | None = None
    settled_history: list[float] = []


class TopNodesAvailableResponse(BaseModel):
    available: Literal[True]
    run_id: str
    delivery_date: date
    horizon: int
    rows: list[TopNodeRow]
    n_ranked: int
    k: int  # served forecast top-k; the client marks rows outside it after settlement.
    grouping: Literal["study_delivery_day", "exact_settled", "study_essp_missing"]


class TopNodesUnavailableResponse(NodeAnalysisUnavailableResponse):
    pass


# ---- /analysis/grade -----------------------------------------------------

class GradeMetricsResponse(BaseModel):
    """The v6 prototype's independent daily-grade measures."""
    detection_ap: float | None
    magnitude_overlap: float | None
    timing_daily_skill: float | None
    timing_hourly_skill: float | None
    top_decile_daily_capture: float | None = None
    top_decile_hourly_capture: float | None = None


class GradeSupportResponse(BaseModel):
    daily_bound_count: int
    hourly_bound_count: int
    forecast_total: float
    settled_total: float
    daily_bound_rate: float
    hourly_bound_rate: float
    forecast_to_settled_ratio: float | None
    magnitude_ceiling: float | None
    magnitude_of_ceiling: float | None


class BriefSourceMetrics(BaseModel):
    id: str
    metrics: GradeMetricsResponse


class GradeHalfResponse(BaseModel):
    """One unblended constraint or node grade half."""
    graded: bool
    unavailable_reason: str | None = None
    universe_size: int | None = None
    support: GradeSupportResponse | None = None
    sources: list[SourceDescriptor] = []
    source_metrics: list[BriefSourceMetrics] = []


class GradeAvailableResponse(BaseModel):
    available: Literal[True]
    run_id: str
    delivery_date: date
    horizon: int
    constraints: GradeHalfResponse
    nodes: GradeHalfResponse


class GradeUnavailableResponse(NodeAnalysisUnavailableResponse):
    pass


class GradeHistoryHalfResponse(BaseModel):
    sources: list[SourceDescriptor] = []
    source_metrics: list[BriefSourceMetrics] = []


class GradeHistoryDayResponse(BaseModel):
    delivery_date: date
    constraints: GradeHistoryHalfResponse
    nodes: GradeHistoryHalfResponse


class GradeHistoryAvailableResponse(BaseModel):
    available: Literal[True]
    run_id: str
    delivery_date: date
    horizon: int
    days: list[GradeHistoryDayResponse]


class GradeHistoryUnavailableResponse(NodeAnalysisUnavailableResponse):
    pass


# ---- /analysis/brief ------------------------------------------------------

class BriefHeroShellResponse(BaseModel):
    """The Brief's first paint: hero plus lightweight delivery-day navigation."""
    hero: HeroAvailableResponse | HeroUnavailableResponse | HeroUnavailableAtHorizonResponse
    previous_delivery_date: date | None = None
    next_delivery_date: date | None = None


class BriefHeroStatsResponse(BaseModel):
    """The Brief hero's complete stat-card evidence, loaded as one group."""
    run_id: str
    delivery_date: date
    horizon: int
    slots: dict[str, dict[str, Any]]


class BriefDetailsResponse(BaseModel):
    """The secondary Brief panels, intentionally separate from the hero shell."""
    context: ContextAvailableResponse | ContextUnavailableResponse
    standouts: StandoutsAvailableResponse | StandoutsUnavailableResponse | None = None
    top_nodes: TopNodesAvailableResponse | TopNodesUnavailableResponse
    top_constraints: TopConstraintsAvailableResponse | TopConstraintsUnavailableResponse
    grade: GradeAvailableResponse | GradeUnavailableResponse
    grade_history: GradeHistoryAvailableResponse | GradeHistoryUnavailableResponse
class BriefDayResponse(BaseModel):
    """One bundled payload for a Brief delivery day (0137).

    Replaces the eight-request per-day fan-out with a single call; each field
    keeps the exact response shape its single-section endpoint already served,
    so consumers built against those shapes are untouched.
    """
    hero: HeroAvailableResponse | HeroUnavailableResponse | HeroUnavailableAtHorizonResponse
    context: ContextAvailableResponse | ContextUnavailableResponse
    standouts: StandoutsAvailableResponse | StandoutsUnavailableResponse
    top_nodes: TopNodesAvailableResponse | TopNodesUnavailableResponse
    top_constraints: TopConstraintsAvailableResponse | TopConstraintsUnavailableResponse
    grade: GradeAvailableResponse | GradeUnavailableResponse
    grade_history: GradeHistoryAvailableResponse | GradeHistoryUnavailableResponse
