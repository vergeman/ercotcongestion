"""Response schemas for the API."""

from datetime import date, datetime

from pydantic import BaseModel


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
    sps: list[ErcotSpSpp]


class ErcotSppRangeResponse(BaseModel):
    start: datetime
    end: datetime
    count: int
    entries: list[ErcotSppRangeEntry]


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
    """
    start: datetime
    end: datetime
    run_id: str
    count: int
    entries: list[ForecastRangeEntry]


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


class ConstraintReach(BaseModel):
    """Top-k nodes one constraint drives — the constraint click.

    ``sps`` carries the signed reach so the client can glow the positive- and
    negative-SF ends opposite (spec §4), placing each end from the per-node
    coords. Signed detail, caveated by ``oos_r2``/``sf_stability``.
    """
    constraint_key: str
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


class ConstraintLobe(BaseModel):
    """One end of a constraint's congestion dipole — its source (import, SF<0) or
    sink (export, SF>0) lobe. ``n_nodes`` counts the located nodes above the floor
    on that side; the panel's dipole gauge is split by the two sides' counts. Zero
    for a one-sided or unlocated constraint (a lobe with no nodes)."""
    n_nodes: int = 0


class RankedConstraint(BaseModel):
    """One constraint in the per-day ranking (a /map/constraints/ranked row).

    ``congestion_contribution = mu_mass · reach`` is the sort key (descending);
    ``rank`` is its 1-based position. ``source_lobe``/``sink_lobe`` carry the
    congestion dipole (import vs export node counts); ``n_members`` is the located
    node count above the floor. ``ctype`` mirrors the /map/overview marker (same
    ``constraint_id`` key), so a panel row highlights the same overlay mark.
    ``mu_mass``/``reach`` are exposed so the contribution is legible, not a
    black-box score."""
    constraint_id: str
    rank: int
    congestion_contribution: float
    mu_mass: float
    reach: float
    n_members: int
    ctype: str | None = None
    source_lobe: ConstraintLobe
    sink_lobe: ConstraintLobe


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
