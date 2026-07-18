"""Response schemas for the API."""

from datetime import datetime

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


class ConstraintGeo(BaseModel):
    """One constraint at its |SF|-weighted centroid — the overlay marker.

    ``spread_km`` large is a multimodality caution: a bimodal constraint's
    centroid can land between its lobes (spec §1.2).
    """
    constraint_key: str
    lat: float | None = None
    lon: float | None = None
    zone_shares: dict[str, float] | None = None
    kv_mean: float | None = None
    kv_max: float | None = None
    spread_km: float | None = None
    max_abs_sf: float | None = None
    n_rail: int | None = None          # nodes pinned at the ±1 clamp (|SF|>=0.999)
    peak_offrail: float | None = None  # top of the graded body beneath the rail
    binding_hours: int | None = None


class SpExposure(BaseModel):
    """One constraint driving the queried node (a ``/map/exposures`` row).

    ``sf`` is the signed exposure ($/MWh per $ of μ) — caveated, read it
    against the response's window confidence. ``lat``/``lon`` are the
    constraint's centroid, for highlighting on the map.
    """
    constraint_key: str
    sf: float
    lat: float | None = None
    lon: float | None = None
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

    ``lat``/``lon`` are the constraint's own centroid; ``sps`` carries the
    signed reach so the client can glow the positive- and negative-SF ends
    opposite (spec §4). Signed detail, caveated by ``oos_r2``/``sf_stability``.
    """
    constraint_key: str
    run_id: str
    window_start: datetime
    window_end: datetime
    k: int
    oos_r2: float | None = None
    sf_stability: float | None = None
    lat: float | None = None
    lon: float | None = None
    max_abs_sf: float | None = None
    n_rail: int | None = None
    peak_offrail: float | None = None
    binding_hours: int | None = None
    sps: list[ReachSp]


class OverviewConstraint(BaseModel):
    """One constraint in the de-piled overview (a ``/map/overview`` row).

    Positioned at its ``core_lat``/``core_lon`` — the ``|SF|²``-weighted geometric
    median, which sits on the constraint's strongest lobe rather than averaging to
    the empty center the way ``lat``/``lon`` (the ``|SF|``-mean centroid) does.
    ``ctype`` (``gtc``/``transmission``/``radial``) picks the mark's *form*;
    ``nodes`` carries the signed top-K field the client draws the mark over and the
    drill-down colors (the overview itself ignores the sign). ``core_lat``/``lon``
    are NULL for an unlocatable constraint (holes stay holes).
    """
    constraint_key: str
    ctype: str | None = None
    binding_hours: int | None = None
    max_abs_sf: float | None = None
    core_lat: float | None = None
    core_lon: float | None = None
    lat: float | None = None          # |SF|-mean centroid, for reference
    lon: float | None = None
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
