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


# ---- /api/meta -----------------------------------------------------------

class MetaResponse(BaseModel):
    """What the API is currently serving. Read-only surface for debug UI.

    ``run_id``, ``ref``, ``algo``, ``k`` are derived from the served
    scorecard cell. ``promoted_at`` is retired and always ``null`` — the
    binding-proximity DB pointer it reported is gone; the field is kept so
    the JSON shape stays stable for existing clients. The scorecard fields
    are ``None`` when no cell has been promoted yet.
    """
    run_id: str | None = None
    ref: str | None = None
    algo: str | None = None
    k: int | None = None
    promoted_at: datetime | None = None


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
