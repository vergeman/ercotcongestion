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


# ---- /analysis/node and /analysis/path ----------------------------------

class AnalysisContributionTerm(BaseModel):
    constraint_key: str
    contribution: float
    shift_factor: float


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


class NodeAnalysisUnavailableResponse(BaseModel):
    available: Literal[False]
    unavailable_reason: Literal["artifact_missing"]
    run_id: str
    delivery_date: date
    horizon: int | None = None


class PathComposition(BaseModel):
    top_share: float
    second_share: float
    tail_share: float
    n_terms: int
    top_constraint_key: str | None
    second_constraint_key: str | None


class PathAnalysisAvailableResponse(BaseModel):
    available: Literal[True]
    source: str
    sink: str
    run_id: str
    delivery_date: date
    horizon: int
    basis: Literal["predicted", "realized"]
    hours: list[datetime]
    spread: float
    n_terms: int
    composition: PathComposition
    terms: list[AnalysisContributionTerm]


class PathAnalysisUnavailableResponse(NodeAnalysisUnavailableResponse):
    pass


class AnalysisSettlementPointsAvailableResponse(BaseModel):
    """The exact settlement-point vocabulary represented by one day artifact."""
    available: Literal[True]
    run_id: str
    delivery_date: date
    horizon: int
    settlement_points: list[str]


class AnalysisSettlementPointsUnavailableResponse(NodeAnalysisUnavailableResponse):
    pass


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
    include_below_floor: bool
    serving_floor_abs: float
    n_fit_constraints: int
    rows: list[ForecastMuRow]
    missing_constraint_keys: list[str]


class ForecastMuUnavailableResponse(NodeAnalysisUnavailableResponse):
    pass


# ---- /api/ercot_state_range ---------------------------------------------
#
# Per-hour ERCOT settlement-point congestion, read from the active run's
# congestion_matrices.npz.

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
    total_load_mw: float | None = None
    sps: list[ErcotSpSpp]


class ErcotSppRangeResponse(BaseModel):
    start: datetime
    end: datetime
    count: int
    entries: list[ErcotSppRangeEntry]


# ---- /ercot_range --------------------------------------------------------
#
# Compact wire format for the two realized ERCOT views.  Settlement-point IDs
# are static across a requested window, so send them once and align each
# hour's value arrays to that index.  The browser expands this at its API edge
# into the small object shape its map code already consumes.

class ErcotRangeEntry(BaseModel):
    interval_ts: datetime
    total_load_mw: float | None = None
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
# Per-hour, per-SP forecast congestion (P10/P50/P90) over a window — the
# prediction counterpart to ``/ercot_spp_range``, read from ``forecast_nodal``
# at the current ``forecast_current[ercot]`` run. Same range shape (start / end /
# count / per-hour ``entries``) so the left ("prediction") map pane aligns to the
# same scrubber the realized right pane does, hour for hour, instead of both
# rendering one realized quantity.
#
# Expanded for prediction: each SP carries the P10/P50/P90 triple (not a single
# price), and each hour carries the DAM ``system_lambda`` (NP4-523-CD) at that
# interval so the client resolves predicted LMP = P50 + system_λ — the same
# reference the market side subtracts, so the LMP-basis comparison collapses to
# the congestion-basis one (plan 0096/0098). ``run_id`` labels which refit is
# serving; the served day is the cursor hour's date.

class ForecastSpState(BaseModel):
    """One SP's forecast congestion at one hour — a ``forecast_nodal`` row.

    ``p50`` is the sampling-median congestion the prediction pane fills with;
    ``p10``/``p90`` bracket it. All nullable — a NaN percentile persisted as NULL
    rides through as ``None`` rather than dropping the SP.
    """
    sp_id: str
    p10: float | None = None
    p50: float | None = None
    p90: float | None = None


class ForecastRangeEntry(BaseModel):
    """All SPs' forecast congestion at one interval, plus that hour's system-λ.

    ``system_lambda`` is the DAM system-λ at ``interval_ts``; ``None`` when no λ
    is published for the hour (LMP then falls back to unset on the prediction
    side). Add it to each SP's congestion for the predicted LMP palette.
    """
    interval_ts: datetime
    system_lambda: float | None = None
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
    """
    constraint_key: str
    ctype: str | None = None
    sf: float
    max_abs_sf: float | None = None
    binding_hours: int | None = None


class ExposuresResponse(BaseModel):
    """Top-k constraints driving one node — the node-explorer click.

    ``node_max_abs_sf`` = ``max_c |SF[sp,c]|`` is the stable, unsigned
    headline (spec §6); the per-constraint signed exposures follow,
    caveated by ``oos_r2``/``sf_stability``.
    """
    sp: str
    run_id: str
    window_start: datetime
    window_end: datetime
    k: int
    oos_r2: float | None = None
    sf_stability: float | None = None
    node_max_abs_sf: float | None = None
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
    coords. Signed detail, caveated by ``oos_r2``/``sf_stability``.
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
    # False means the requested key has no represented SF reach in the active
    # fit/window; callers can distinguish it from an empty visual selection.
    available: bool = True
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
    panel row highlights the same overlay mark. ``mu_mass``/``reach`` are exposed so
    the contribution is legible, not a black-box score."""
    constraint_id: str
    rank: int
    congestion_contribution: float
    mu_mass: float
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
    """Row-major recovered implied-SF values aligned to ``rows`` and ``columns``."""
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
    currency: str            # topdecile_hit | rank_spearman | sign_agree | pooled_r2
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
    board (0002); the headline never redefines a gate, it summarizes served cells.
    """
    window_days: int         # 30 | 90
    weeks: int
    week_start: date
    week_end: date
    currencies: list[HeadlineCurrency]


class ScoreboardHeadline(BaseModel):
    """The rolling headline for one board (``run_id``) and ``regime``.

    ``run_id`` is the model version whose backtest this is; ``as_of_week`` is the
    latest week on the board (the anchor the rolling windows trail from). The
    served ``regime`` echoes the request (default ``all``).
    """
    run_id: str
    regime: str
    as_of_week: date
    windows: list[HeadlineWindow]


# ---- /scoreboard/weekly --------------------------------------------------
#
# The full weekly backtest series (plan/0102 §0002, spec-phase3 §3/§5/§7) — the
# data behind the scoreboard *page* the panel's "View full scoreboard" link
# targets. Every response carries all sources (model + baselines + oracle) so a
# lone model figure can't be rendered (§6), plus a pooled pre/post-RTC+B summary
# with the pre-registered ``gate()`` verdict transcribed as-is (never redefined).


class WeeklyPoint(BaseModel):
    """One ``scoreboard_weekly`` row served for the chart — one (week, source).

    Screening currencies (``rank_spearman``/``sign_agree``/``topdecile_hit``) lead
    the page; magnitude (``pooled_r2``/``mae``) files under a toggle (§6). The band
    columns are populated on the model/all rows only. All nullable — a NULL cell
    (e.g. the flat ``null`` source's declined top-decile) rides through as ``None``.
    """
    week: date
    source: str
    pooled_r2: float | None = None
    mae: float | None = None
    rank_spearman: float | None = None
    sign_agree: float | None = None
    topdecile_hit: float | None = None
    coverage80: float | None = None
    band_width: float | None = None
    pinball: float | None = None
    sf_coverage: float | None = None
    model_coverage: float | None = None
    n_hours: int | None = None
    n_nodes: int | None = None


class SourcePooled(BaseModel):
    """One source's pooled currencies over a split — the week-mean of each metric
    (the same reduction ``r5()``/``cell()`` uses, so the numbers match the
    pre-registered readout). ``None`` when the source had no scored week."""
    source: str
    pooled_r2: float | None = None
    mae: float | None = None
    rank_spearman: float | None = None
    sign_agree: float | None = None
    topdecile_hit: float | None = None


class WeeklySplit(BaseModel):
    """A pooled slice — ``all`` / ``pre_rtc_b`` / ``post_rtc_b`` — so the RTC+B
    structural break is visible on every pooled stat (§5): pooled must not launder
    the post-cutover number. ``gate`` is the pre-registered ``gate()`` run on the
    model's pooled means (``None`` when the model source is absent);
    ``beats_persistence`` is the existence test (model > persistence on all three
    screening currencies). ``sources`` always includes model + persistence +
    climatology + oracle (§6)."""
    label: str            # all | pre_rtc_b | post_rtc_b
    n_weeks: int
    sources: list[SourcePooled]
    gate: str | None = None
    beats_persistence: bool | None = None


class ScoreboardWeekly(BaseModel):
    """The weekly series + pooled summary for one board and ``regime``.

    ``primary_source`` echoes the requested ``source`` (the series the page
    foregrounds); the comparators ride along in ``points`` regardless, so the
    client can never render a lone model figure. ``rtc_b_cutover`` is the split
    date the ``pre_``/``post_rtc_b`` summaries divide on.
    """
    run_id: str
    regime: str
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

    Same currency columns as ``WeeklyPoint``. The band columns (``coverage80`` /
    ``band_width`` / ``pinball``) are populated on the model source only — measured
    live from the served p10/p50/p90 vs realized. ``model_coverage`` is NULL for
    now (it needs the prediction-time key set, the deferred snapshot); ``sf_coverage``
    rides along so a collapse day reads as a coverage gap, not lost skill. All
    nullable — a declined/flat cell (e.g. the ``null`` source's screening) is ``None``.
    """
    delivery_date: date
    source: str
    pooled_r2: float | None = None
    mae: float | None = None
    rank_spearman: float | None = None
    sign_agree: float | None = None
    topdecile_hit: float | None = None
    coverage80: float | None = None
    band_width: float | None = None
    pinball: float | None = None
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
    """
    run_id: str
    since: date | None = None
    primary_source: str
    points: list[DailyPoint]
