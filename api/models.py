"""Response schemas for the API."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


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


class GradeHalfResponse(BaseModel):
    """One unblended constraint or node grade half."""
    graded: bool
    unavailable_reason: str | None = None
    universe_size: int | None = None
    model: GradeMetricsResponse | None = None
    persistence: GradeMetricsResponse | None = None
    climatology: GradeMetricsResponse | None = None
    support: GradeSupportResponse | None = None


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
    model: GradeMetricsResponse
    persistence: GradeMetricsResponse


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


# ---- /ercot_range --------------------------------------------------------
#
# Compact wire format for the two realized ERCOT views.  Settlement-point IDs
# are static across a requested window, so send them once and align each
# hour's value arrays to that index.  The browser expands this at its API edge
# into the small object shape its map code already consumes.

class ErcotRangeEntry(BaseModel):
    interval_ts: datetime
    # One DAM system reference price per interval. It is sent alongside the
    # compact SPP/congestion arrays so timeline-level consumers do not need to
    # reconstruct it from rounded nodal values.
    system_lambda: float | None
    congestion: list[float | None]
    spp: list[float | None]


class ErcotRangeResponse(BaseModel):
    start: datetime
    end: datetime
    count: int
    sp_ids: list[str]
    entries: list[ErcotRangeEntry]


# ---- /forecast_range -----------------------------------------------------
#
# Per-hour, per-SP deterministic forecast congestion over a window — the
# prediction counterpart to ``/ercot_range``, read from ``forecast_nodal``
# at the current ``forecast_current[ercot]`` run. Same range shape (start / end /
# count / per-hour ``entries``) so the left ("prediction") map pane aligns to the
# same scrubber the realized right pane does, hour for hour, instead of both
# rendering one realized quantity.
#
# Each SP carries deterministic congestion, and each hour carries the DAM
# ``system_lambda`` (NP4-523-CD) so predicted LMP = forecast_congestion + system_λ.
# This is the same
# reference the market side subtracts, so the LMP-basis comparison collapses to
# the congestion-basis one (plan 0096/0098). ``run_id`` labels which refit is
# serving; the served day is the cursor hour's date.

class ForecastSpState(BaseModel):
    """One SP's forecast congestion at one hour — a ``forecast_nodal`` row.

    ``forecast_congestion`` is ``−(E_mu · SF)``. It is nullable so an invalid
    persisted value remains explicit rather than dropping the settlement point.
    """
    sp_id: str
    forecast_congestion: float | None = None


class ForecastRangeEntry(BaseModel):
    """All SPs' forecast congestion at one interval, plus that hour's system-λ.

    ``system_lambda`` is the DAM system-λ at ``interval_ts`` when settled;
    on an unsettled hour it falls back to the most recent settled day's λ at
    the same Central hour (a persistence curve — display only, never graded),
    and ``None`` only when no settled day exists yet to persist from.
    ``lambda_source`` says which: ``"settled"`` or ``"persisted"``. Add
    ``system_lambda`` to each SP's congestion for the predicted LMP palette.
    """
    interval_ts: datetime
    system_lambda: float | None = None
    lambda_source: Literal["settled", "persisted"] | None = None
    sps: list[ForecastSpState]


class ForecastRangeResponse(BaseModel):
    """Per-hour forecast congestion across a window for the current forecast run.

    ``run_id`` (model version) labels which refit is serving; ``entries`` are the
    forecast hours falling in ``[start, end]`` for that run, so a window covering
    the served delivery day renders the forecast aligned to the realized ranges.

    ``horizons`` is the per-delivery-day provenance map (``"YYYY-MM-DD" -> 1|2``,
    0123): which horizon each served day came from — 1 = final/t+1, 2 = preview/t+2.
    Absent an explicit ``?horizon=``, the endpoint coalesces per day (prefer final,
    fall back to preview) into one continuous series; this map is how a client knows
    which days are still previews without changing the series shape.
    """
    start: datetime
    end: datetime
    run_id: str
    count: int
    entries: list[ForecastRangeEntry]
    horizons: dict[str, int] = {}


# ---- /map/* --------------------------------------------------------------
#
# The implied shift-factor map (spec-phase1-serve-map §3). SF *structure* —
# which constraints drive which nodes, and where those constraints live —
# on top of the Phase-0 realized-congestion node coloring. Not time-indexed:
# the SF structure is fixed per refit, so every response describes one
# resolved (run_id, window_start) refit, not an hour.
#
# Identifiability guardrail (spec §6): the stable, unsigned magnitude
# (``max_abs_sf`` per constraint, ``node_max_abs_sf`` per node) is the
# headline; signed ``sf`` is the caveated detail and always ships with its
# window ``oos_r2``/``sf_stability`` so a flickering attribution reads as
# low-confidence.


class MapMeta(BaseModel):
    """The current refit the map is serving — one ``sf_window_meta`` row."""
    run_id: str
    window_start: datetime
    window_end: datetime
    fit_r2: float | None = None
    oos_r2: float | None = None
    coverage: float | None = None
    sf_stability: float | None = None
    n_kept: int | None = None


class SpExposure(BaseModel):
    """One constraint driving the queried node (a ``/map/exposures`` row).

    ``sf`` is the signed exposure ($/MWh per $ of μ) — caveated, read it
    against the response's window confidence.

    ``contribution`` = ``-sf * mu`` is the constraint's actual $/MWh of this
    node's congestion at the requested interval, and is what ``rank=contribution``
    orders by; both it and ``mu`` are ``None`` under ``rank=sf``, which describes
    structure and has no hour attached.

    ``sf_clipped`` marks a cell the ridge fit pinned at its ``SF_ABS_CAP`` of
    1.0 (``compute/sf/fit.py``). It is a bound, not a measurement — a
    poorly-conditioned column, not a node that moves 1:1 with the constraint —
    and matters out of proportion to how rare it is, because a clipped value is
    by construction the largest possible ``|SF|`` and so always sorts first
    under ``rank=sf``.
    """
    constraint_key: str
    ctype: str | None = None
    sf: float
    sf_clipped: bool = False
    mu: float | None = None
    contribution: float | None = None
    max_abs_sf: float | None = None
    binding_hours: int | None = None


class ExposuresResponse(BaseModel):
    """Top-k constraints driving one node — the node-explorer click.

    ``node_max_abs_sf`` = ``max_c |SF[sp,c]|`` is the stable, unsigned
    headline (spec §6); the per-constraint signed exposures follow.

    Served from the requested day's SF artifact (0144), so the values match
    ``/matrix/frame`` at the same node and interval. ``window_start``/
    ``window_end`` bound that day's block rather than a rolling fit window, and
    ``oos_r2``/``sf_stability`` are ``None`` — they describe the rolling
    ``sf_window_meta`` fit, which no longer backs these numbers.

    ``rank`` names the basis the list is ordered on, because that — not the SF
    values, which agree everywhere — is what made this endpoint appear to
    contradict the matrix (0145):

    * ``contribution`` (default): what actually drove the node at ``t``, ordered
      by ``|-SF * mu|`` with ``mu = 0`` rows dropped. Matches
      ``/analysis/node``'s ``terms``. ``node_gross_total`` is the sum of all
      absolute contributions; it is the denominator for a bounded
      driver-magnitude share, so opposing signs do not turn a near-zero net
      into an arbitrary percentage.
    * ``sf``: structural exposure, ordered by ``|SF|`` over every constraint in
      the day's fit including those that never bound. ``node_gross_total`` is
      ``None``.
    """
    sp: str
    run_id: str
    window_start: datetime
    window_end: datetime
    k: int
    rank: Literal["contribution", "sf"] = "contribution"
    node_gross_total: float | None = None
    oos_r2: float | None = None
    sf_stability: float | None = None
    node_max_abs_sf: float | None = None
    # False = no SF to report: ``artifact_missing`` (no artifact for the day),
    # ``interval_not_in_artifact`` (block does not cover ``t``),
    # ``sp_not_in_service`` (the node did not exist on this day), or
    # ``sp_not_in_fit`` (it existed but the fit dropped it).
    # Distinct from a node in the fit that drives nothing: available, empty.
    available: bool = True
    unavailable_reason: str | None = None
    exposures: list[SpExposure]


class ReachSp(BaseModel):
    """One node a constraint drives (a ``/map/reach`` row).

    Signed ``sf`` splits the driven nodes into the constraint's import and
    export ends (the congestion dipole); ``lat``/``lon`` place the node.
    """
    settlement_point: str
    sf: float
    lat: float | None = None
    lon: float | None = None
    settlement_point_type: str | None = None
    load_zone: str | None = None


class ConstraintReach(BaseModel):
    """Top-k nodes one constraint drives — the constraint click.

    ``sps`` carries the signed reach so the client can glow the positive- and
    negative-SF ends opposite (spec §4), placing each end from the per-node
    coords.

    Served from the requested day's SF artifact (0144) — see
    ``ExposuresResponse`` for what that means for ``window_start``/``window_end``
    and ``oos_r2``/``sf_stability``.

    ``full=True`` switches the query to the unbounded reach (bounded only by
    ``min_frac``) the matrix Read pane needs (plan/0139-0001) instead of a
    display top-k; ``truncated`` reports whether a bounded (``full=False``)
    call was cut short of the complete reach, independent of which mode was
    used — always ``False`` when ``full=True``, since that mode is complete by
    construction.
    """
    constraint_key: str
    ctype: str | None = None
    run_id: str
    window_start: datetime
    window_end: datetime
    k: int
    oos_r2: float | None = None
    sf_stability: float | None = None
    max_abs_sf: float | None = None
    n_rail: int | None = None
    peak_offrail: float | None = None
    binding_hours: int | None = None
    # Forecast μ from this constraint's daily artifact at the requested cursor
    # interval. Null when the request has no cursor hour or the served SF is a
    # nearest-past structural fallback rather than that interval's artifact.
    shadow_price: float | None = None
    # Published ERCOT DAM μ for the same cursor interval/key. It remains null
    # until publication; forecast_error is never manufactured from missing DAM.
    dam_mu: float | None = None
    forecast_error: float | None = None
    # Daily forecast-μ magnitude and rank from the served artifact's complete
    # constraint vocabulary, plus the unfiltered nonzero-SF dipole counts.
    daily_mu_rank: int | None = None
    daily_mu_sum: float | None = None
    import_members: int | None = None
    export_members: int | None = None
    # False means the requested key has no represented SF reach on the requested
    # day (or the day has no artifact); callers can distinguish it from an empty
    # visual selection.
    available: bool = True
    unavailable_reason: str | None = None
    # Provenance of the SF served. 'artifact' = the requested delivery day's own
    # artifact (0144, day-exact). 'nearest_past' = that day had no artifact (a
    # lagging or failed forecast job, or a day ahead of the newest build), so the
    # nearest EARLIER built day's artifact was served instead — SF is
    # topology-driven and drifts slowly. ``window_start``/``window_end`` report the
    # day actually served, so the client can label it "SF as of <date>".
    basis: str = "artifact"
    truncated: bool = False
    sps: list[ReachSp]


class OverviewConstraint(BaseModel):
    """One constraint in the de-piled overview (a ``/map/overview`` row).

    ``ctype`` (``gtc``/``transmission``/``radial``) picks the mark's *form*;
    ``nodes`` carries the signed top-K field the client draws the mark over — and
    anchors it, positioning the radial ring on the peak-|SF| node rather than a
    persisted centroid. The client also uses ``nodes`` for the drill-down colors
    (the overview itself ignores the sign).
    """
    constraint_key: str
    ctype: str | None = None
    binding_hours: int | None = None
    max_abs_sf: float | None = None
    nodes: list[ReachSp]


class MapOverview(BaseModel):
    """The whole overview for the current refit — top-``n`` constraints by binding
    hours, each at its core with its type and signed top-``k`` node field.

    One bulk payload so the client renders the de-piled map from a single window
    slice; signed detail is caveated by ``oos_r2``/``sf_stability``.
    """
    run_id: str
    window_start: datetime
    window_end: datetime
    n: int
    k: int
    oos_r2: float | None = None
    sf_stability: float | None = None
    constraints: list[OverviewConstraint]


# ---- /map/constraints/ranked ---------------------------------------------
#
# The per-day ranked constraint list (plan/0103) — "which constraints drive
# today's congestion", the list-shaped companion to the /map/overview marker
# pile the panel cannot express. Ranked by a day-total congestion contribution
# ``mu_mass · reach``, the day-aggregate of the ``−E_mu·SF`` decomposition
# node_drivers already uses: ``mu_mass = Σ_ts |μ[ts,c]|`` (the constraint's total
# shadow-price mass over the delivery day) times ``reach = Σ_sp |SF[c,sp]|`` (how
# far that price propagates into nodal congestion). Two bases share one SF
# structure, differing only in the μ series: ``predicted`` reads the day's fitted
# E_mu from ``forecast_sf_artifact``; ``realized`` swaps in that day's published
# DAM shadow prices (``ercot_dam_shadow_prices``, joined on the same
# ``constraint_name|contingency_name`` key the SF panel is built from).


class RankedConstraint(BaseModel):
    """One constraint in the per-day ranking (a /map/constraints/ranked row).

    ``congestion_contribution = mu_mass · reach`` is the sort key (descending);
    ``rank`` is its 1-based position. ``n_import``/``n_export`` carry the congestion
    dipole — located nodes above the floor on the import (SF<0) and export (SF>0)
    sides, which the panel's dipole gauge is split by; ``n_members`` is their total.
    ``ctype`` mirrors the /map/overview marker (same ``constraint_id`` key), so a
    panel row highlights the same overlay mark. The daily μ fields
    (``mu_mass``, ``binding_hours``) follow the requested basis; ``reach`` comes
    from the shared artifact structure and therefore does not. Together they make
    the contribution legible, not a black-box score."""
    constraint_id: str
    rank: int
    congestion_contribution: float
    mu_mass: float
    binding_hours: int
    reach: float
    n_members: int
    ctype: str | None = None
    n_import: int = 0
    n_export: int = 0


class RankedConstraints(BaseModel):
    """The per-day ranked constraint list for one forecast run and basis.

    ``run_id`` is the forecast model version whose SF+μ artifact backs the ranking;
    ``delivery_date`` is the ranked day; ``basis`` echoes the request
    (``predicted`` | ``realized``). ``n_ranked`` is how many constraints carried a
    non-zero contribution (the pool the top-``k`` is drawn from); ``constraints`` is
    the top-``k`` ordered by contribution."""
    run_id: str
    delivery_date: date
    basis: str
    k: int
    n_ranked: int
    constraints: list[RankedConstraint]


# ---- /matrix/frame -------------------------------------------------------

class MatrixRow(BaseModel):
    """One stable constraint row in a delivery day's bounded SF rectangle."""
    constraint_key: str
    constraint_name: str
    contingency_name: str | None = None
    constraint_type: str | None = None
    forecast_mu: float
    ercot_dam_mu: float | None = None
    daily_rank: int
    binding_hours: int
    max_abs_sf: float


class MatrixColumn(BaseModel):
    """One stable settlement-point column in a bounded SF rectangle."""
    settlement_point: str
    settlement_point_type: str | None = None
    load_zone: str | None = None
    max_abs_sf: float


class MatrixSfValues(BaseModel):
    """Row-major recovered implied-SF values aligned to ``rows`` and ``columns``.

    A cell whose ``|value|`` equals the frame's ``sf_abs_cap`` was pinned there
    by the ridge fit's clip and is a bound rather than a measurement (0145). No
    parallel mask is sent: the clip is exact, so ``abs(v) >= sf_abs_cap`` is the
    same test the server would apply, at a fraction of the payload.
    """
    row_count: int
    column_count: int
    values: list[float]


class MatrixFrame(BaseModel):
    """A causal, immutable-artifact-backed Matrix frame for one delivery hour."""
    available: bool
    unavailable_reason: str | None = None
    run_id: str
    delivery_date: date
    interval_ts: datetime
    fit_window_start: datetime | None = None
    fit_window_end: datetime | None = None
    # Which axis got the "primary list" (ranked + searched + bounded) treatment.
    # The wire shape is unchanged — ``rows`` are always constraints and
    # ``columns`` always settlement points — but the client reads this to decide
    # the visual orientation (``nodes`` renders nodes as rows by transposing).
    orientation: Literal['constraints', 'nodes'] = 'constraints'
    dam_status: Literal['pending', 'partial', 'available'] = 'pending'
    row_ordering: str = 'daily_abs_forecast_contribution_desc_then_constraint_key'
    column_ordering: str = 'max_abs_sf_desc_then_settlement_point'
    # The bounded rectangle is intentionally not the whole artifact.  Clients
    # need this distinction before describing any visible-only sum.
    rows_truncated: bool = False
    columns_truncated: bool = False
    # Counts describe the artifact universe, not a congestion total.  A client
    # can therefore say "30 of 143 constraints" without implying that the
    # visible rows account for all nodal congestion.
    total_constraint_count: int = 0
    total_settlement_point_count: int = 0
    # Day-wide extrema keep the color legend stable when a client filters the
    # bounded view. Contribution uses the forecast-day range for both sources
    # so their colors remain directly comparable.
    sf_day_max_abs: float = 0.0
    contribution_day_max_abs: float = 0.0
    # The fit's |SF| clip. Cells sitting exactly here were pinned by the ridge
    # rather than measured, and the client marks them; sent so the threshold has
    # one source (compute.sf_map.model.fit.SF_ABS_CAP) instead of a hardcoded 1.0 on both
    # sides of the wire.
    sf_abs_cap: float = 0.0
    rows: list[MatrixRow] = []
    columns: list[MatrixColumn] = []
    sf: MatrixSfValues


# ---- /scoreboard/headline ------------------------------------------------
#
# The backtest scoreboard's rolling headline (plan/0102 §0001, spec-phase3
# §3/§6). Rolling 30/90-day tiles read from ``scoreboard_weekly`` — the thin
# panel view, not the full board (that is 0002). The one non-negotiable: a
# model figure never ships alone. Every currency carries its ``persistence``
# delta and the ``oracle`` ceiling (and ``climatology`` for context), so the
# client cannot render a lone model number (§6 integrity rule).


class HeadlineCurrency(BaseModel):
    """One pre-registered currency in one rolling window, model + its comparators.

    ``model`` never travels without ``persistence``/``climatology``/``oracle`` —
    the integrity rule (spec §6). ``persistence_delta = model - persistence`` is
    the raw delta; read its sign against ``higher_is_better`` (all current
    currencies are higher-is-better, so a positive delta means the model beats
    persistence). ``oracle`` is the ceiling the model is measured against. Any
    value can be ``None`` when a source had no scored week in the window.
    """
    currency: str            # topdecile_hit | rank_spearman | sign_agree
    higher_is_better: bool
    model: float | None = None
    persistence: float | None = None
    climatology: float | None = None
    oracle: float | None = None
    persistence_delta: float | None = None   # model - persistence (raw, sign per flag)


class HeadlineWindow(BaseModel):
    """One rolling window (30d / 90d) — every currency pooled over the trailing
    weeks. ``weeks`` is how many weekly rows fed the pool; ``week_start``/
    ``week_end`` bound them. The pool is an ``n_hours``-weighted mean of the weekly
    cells — an approximation of the fully pooled stat, which lives on the full
    board (0002).
    """
    window_days: int         # 30 | 90
    weeks: int
    week_start: date
    week_end: date
    currencies: list[HeadlineCurrency]


class ScoreboardHeadline(BaseModel):
    """The rolling headline for one board (``run_id``).

    ``run_id`` is the model version whose backtest this is; ``as_of_week`` is the
    latest week on the board (the anchor the rolling windows trail from).
    """
    run_id: str
    as_of_week: date
    windows: list[HeadlineWindow]


# ---- /scoreboard/weekly --------------------------------------------------
#
# The full weekly backtest series (plan/0102 §0002, spec-phase3 §3/§5/§7) — the
# data behind the scoreboard *page* the panel's "View full scoreboard" link
# targets. Every response carries all sources (model + baselines + oracle) so a
# lone model figure can't be rendered (§6), plus a pooled pre/post-RTC+B summary
# with pooled screening summaries.


class WeeklyPoint(BaseModel):
    """One ``scoreboard_weekly`` row served for the chart — one (week, source).

    Screening currencies (``rank_spearman``/``sign_agree``/``topdecile_hit``) lead
    the page. All nullable — a NULL cell
    (e.g. the flat ``null`` source's declined top-decile) rides through as ``None``.
    """
    week: date
    source: str
    rank_spearman: float | None = None
    sign_agree: float | None = None
    topdecile_hit: float | None = None
    sf_coverage: float | None = None
    model_coverage: float | None = None
    n_hours: int | None = None
    n_nodes: int | None = None


class SourcePooled(BaseModel):
    """One source's pooled currencies over a split — the week-mean of each metric
    ``None`` when the source had no scored week."""
    source: str
    rank_spearman: float | None = None
    sign_agree: float | None = None
    topdecile_hit: float | None = None


class WeeklySplit(BaseModel):
    """A pooled slice — ``all`` / ``pre_rtc_b`` / ``post_rtc_b`` — so the RTC+B
    structural break is visible on every pooled stat (§5): pooled must not launder
    the post-cutover number. ``beats_persistence`` is the existence test (model > persistence on all three
    screening currencies). ``sources`` always includes model + persistence +
    climatology + oracle (§6)."""
    label: str            # all | pre_rtc_b | post_rtc_b
    n_weeks: int
    sources: list[SourcePooled]
    beats_persistence: bool | None = None


class ScoreboardWeekly(BaseModel):
    """The weekly series + pooled summary for one board.

    ``primary_source`` echoes the requested ``source`` (the series the page
    foregrounds); the comparators ride along in ``points`` regardless, so the
    client can never render a lone model figure. ``rtc_b_cutover`` is the split
    date the ``pre_``/``post_rtc_b`` summaries divide on.
    """
    run_id: str
    primary_source: str
    rtc_b_cutover: date
    points: list[WeeklyPoint]
    splits: list[WeeklySplit]


# ---- /scoreboard/daily ---------------------------------------------------
#
# The LIVE scoreboard (plan/0102 §0003, spec-phase3 §3) — per-delivery-day grades
# of the SERVED forecast, scored against realized once DAM publishes, the live
# counterpart to the weekly backtest board. Same integrity rule (§6): every
# response carries all sources (model + persistence + climatology + oracle + the
# ``null`` flat tripwire), so a lone model figure can't be rendered. Same
# ``score_matrix`` currency as the weekly board, so a live number and a backtest
# number are directly comparable. (Miss-attribution — /scoreboard/miss — is
# deferred out of 0003; the per-day grade is the shipped live surface.)


class DailyPoint(BaseModel):
    """One ``scoreboard_daily`` row — one (delivery_date, source) live grade.

    Same point-metric currency columns as ``WeeklyPoint``. ``model_coverage`` is NULL for
    now (it needs the prediction-time key set, the deferred snapshot); ``sf_coverage``
    rides along so a collapse day reads as a coverage gap, not lost skill. All
    nullable — a declined/flat cell (e.g. the ``null`` source's screening) is ``None``.

    ``horizon`` names the forecast track the row grades (1 = final, 2 = preview).
    It rides on every point because the board carries one horizon at a time and a
    reader must never have to guess which one it is looking at.
    """
    delivery_date: date
    source: str
    horizon: int
    rank_spearman: float | None = None
    sign_agree: float | None = None
    topdecile_hit: float | None = None
    sf_coverage: float | None = None
    model_coverage: float | None = None
    n_hours: int | None = None
    n_nodes: int | None = None


class ScoreboardDaily(BaseModel):
    """The live per-day grade series for one run since an optional date.

    ``run_id`` is the model version being graded live (the same version the forecast
    served). ``primary_source`` echoes the requested ``source`` (the series the page
    foregrounds); every source rides along in ``points`` regardless, so the client
    can never render a lone model figure. ``since`` echoes the request (``None`` ==
    the run's full live history).

    ``horizon`` is the single track these points grade; ``horizons`` lists every
    track this run has graded, so a client can offer the switch without a second
    request. One board is one horizon: a series mixing final and preview grades
    would silently compare two differently-informed forecasts.
    """
    run_id: str
    since: date | None = None
    primary_source: str
    horizon: int
    horizons: list[int] = []
    points: list[DailyPoint]


# ---- /scoreboard/summary history -----------------------------------------

class ScoreHistoryPoint(BaseModel):
    """One chart point from the weekly backtest or a served final grade."""
    source: str
    cadence: Literal["backtest_weekly", "served_daily"]
    week: date | None = None
    delivery_date: date | None = None
    rank_spearman: float | None = None
    sign_agree: float | None = None
    topdecile_hit: float | None = None
    sf_coverage: float | None = None
    model_coverage: float | None = None
    n_hours: int | None = None
    n_nodes: int | None = None


class ScoreboardHistory(BaseModel):
    """Weekly walk-forward history followed by final served-day grades."""
    primary_source: str
    weekly_run_id: str
    daily_run_id: str | None = None
    boundary_date: date | None = None
    points: list[ScoreHistoryPoint]


# ---- /scoreboard/summary --------------------------------------------------

class BootstrapSectionStatus(BaseModel):
    """Availability and source identity for one independently built section."""
    available: bool
    unavailable_reason: str | None = None
    run_id: str | None = None
    delivery_date: date | None = None
    horizon: int | None = None

class ScoreboardSummaryResponse(BaseModel):
    """One bundled payload for the Scoreboard page summary (0137).

    ``weekly``/``headline`` read ``scoreboard_weekly``; ``daily`` and the final
    served tail of ``history`` resolve independently from ``scoreboard_daily``.
    A field is ``null`` exactly when its source section would 503.
    """
    weekly: ScoreboardWeekly | None
    headline: ScoreboardHeadline | None
    daily: ScoreboardDaily | None
    history: ScoreboardHistory | None
    availability: dict[str, BootstrapSectionStatus]


# ---- /map/summary -----------------------------------------------------------

class MapSummaryResponse(BaseModel):
    """One bundled payload for the Map workspace summary (0137).

    ``topology`` is the raw settlement-point GeoJSON — the unchanged shape
    ``GET /topology`` already serves, not a typed model (topology never was
    one). ``overview``/``meta``/``headline`` keep their own single-section
    shape and are ``null`` exactly when that section's endpoint would 503 (no
    SF window built yet / no scoreboard loaded) — the same soft-fail the
    client already applies per section. ``topology`` itself is not soft-failed:
    a build failure there was never a null-and-continue case for the client
    (``fetchTopology`` has always thrown on a non-503 failure), so this
    composition preserves that rather than inventing a new empty state.
    """
    topology: dict[str, Any]
    overview: MapOverview | None
    meta: MapMeta | None
    headline: ScoreboardHeadline | None
    availability: dict[str, BootstrapSectionStatus]


# ---- /conditions_range -------------------------------------------------------
#
# Per-hour Load / Wind / Solar / Outages, in one response (plan/0141, merged
# from the three original endpoints — load_zone_range, generation_range,
# outages_range — once the frontend settled on showing them as one "Conditions"
# section). Each sub-list carries both `forecast_mw` and `actual_mw` per row so
# a single Conditions row can pick either side client-side (the map's Forecast/
# Market/Compare/Error toggle), with no per-side request or client-side merge.
#
# load   actual (NP6-345-CD, `load_by_zone`) alongside forecast (NP3-561-CD,
#        `load_forecast_zonal`, read at the latest vintage posted no later
#        than `interval_ts` — no lookahead). `zone` is one of the 8 weather
#        zones in `compute.ercot.zones.WEATHER_ZONES`, plus `"system"`.
# wind/solar
#        actual (NP4-732-CD / NP4-737-CD, `wind_hourly_regional` /
#        `solar_hourly_regional`) alongside forecast (`wind_forecast_regional`
#        / `solar_forecast_regional`, STWPF/STPPF, same no-lookahead vintage
#        rule) — NOT the migration-06 actual tables' own forecast-looking
#        columns, which dedup to the most recent posting (~49h after the hour)
#        and are not knowable ahead of time. `region` is one of the 5 wind /
#        6 solar regions, plus `"system"`.
# outages
#        a DIFFERENT quantity from wind/solar — MW currently OFFLINE (NP1-346
#        unplanned resource outages), not MW produced — and a different
#        cadence underneath: `resource_outages` is a daily D-vintage snapshot,
#        not an hourly series, so a day's values repeat across its 24 hourly
#        entries. `fuel` is one of gas/wind/solar/coal/other/hydro, plus
#        `"total"`. `forecast_mw` is the D-1-admissible vintage (mirrors
#        compute.mu_forecast.covariates.outages.exposure's leak boundary) summed over still-
#        expected-out events; `actual_mw` is the newest vintage through the
#        day itself, summed over genuinely-active-at-that-hour events.

class ZoneLoad(BaseModel):
    zone: str
    forecast_mw: float | None
    actual_mw: float | None


class RegionGen(BaseModel):
    region: str
    forecast_mw: float | None
    actual_mw: float | None


class FuelOutage(BaseModel):
    fuel: str
    forecast_mw: float | None
    actual_mw: float | None


class ConditionsEntry(BaseModel):
    interval_ts: datetime
    load: list[ZoneLoad]
    wind: list[RegionGen]
    solar: list[RegionGen]
    outages: list[FuelOutage]


class ConditionsRangeResponse(BaseModel):
    start: datetime
    end: datetime
    count: int
    entries: list[ConditionsEntry]
