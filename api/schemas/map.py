"""Schemas served by map workspace routes."""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel
from api.schemas.common import BootstrapSectionStatus


class MapMeta(BaseModel):
    """The current refit the map is serving — one ``sf_window_meta`` row."""

    run_id: str
    window_start: datetime
    window_end: datetime
    sf_fit_r2: float | None = None
    sf_oos_r2: float | None = None
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
    1.0 (``compute/sf/fit.py``). It is a bound, not a measurement.
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

    ``node_max_abs_sf`` = ``max_c |SF[sp,c]|`` is the stable, unsigned headline
    (spec §6); the per-constraint signed exposures follow.

    ``rank`` names the basis the list is ordered on

    ``contribution`` (default): what actually drove the node at ``t``, ordered
      by ``|-SF * mu|`` with ``mu = 0`` rows dropped. Matches
      ``/analysis/node``'s ``terms``. ``node_gross_total`` is the sum of all
      absolute contributions; it is the denominator for a bounded
      driver-magnitude share, so opposing signs do not turn a near-zero net
      into an arbitrary percentage.

    ``sf``: structural exposure, ordered by ``|SF|`` over every constraint in
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
    sf_oos_r2: float | None = None
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
    negative-SF ends opposite , placing each end from the per-node coords.

    Served from the requested day's SF artifact — see ``ExposuresResponse`` for
    what that means for ``window_start``/``window_end`` and
    ``sf_oos_r2``/``sf_stability``.

    ``full=True`` switches the query to the unbounded reach (bounded only
    by ``min_frac``) instead of a display top-k;


    """

    constraint_key: str
    ctype: str | None = None
    run_id: str
    window_start: datetime
    window_end: datetime
    k: int
    sf_oos_r2: float | None = None
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
    # Provenance of the SF served. 'artifact' = the requested delivery day's
    # own artifact. 'nearest_past' = that day had no artifact (a lagging or
    # failed forecast job, or a day ahead of the newest build), so the nearest
    # EARLIER built day's artifact was served instead — SF is topology-driven
    # and drifts slowly. ``window_start``/``window_end`` report the day
    # actually served, so the client can label it "SF as of <date>".
    basis: str = "artifact"
    truncated: bool = False
    sps: list[ReachSp]


class OverviewConstraint(BaseModel):
    """One constraint in the de-piled overview (a ``/map/overview`` row).

    ``ctype`` (``gtc``/``transmission``/``radial``) picks the mark's *form*;
    ``nodes`` carries the signed top-K field the client draws the mark over,
    and anchors it, positioning the radial ring on the peak-|SF| node rather
    than a persisted centroid. The client also uses ``nodes`` for the
    drill-down colors (the overview itself ignores the sign).

    """

    constraint_key: str
    ctype: str | None = None
    binding_hours: int | None = None
    max_abs_sf: float | None = None
    nodes: list[ReachSp]


class MapOverview(BaseModel):
    """The whole overview for the current refit: top-``n`` constraints by
    binding hours, each at its core with its type and signed top-``k`` node
    field.

    One bulk payload so the client renders the de-piled map from a single
    window slice; signed detail is caveated by ``sf_oos_r2``/``sf_stability``.

    """

    run_id: str
    window_start: datetime
    window_end: datetime
    n: int
    k: int
    sf_oos_r2: float | None = None
    sf_stability: float | None = None
    constraints: list[OverviewConstraint]


# ---- /map/constraints/ranked ---------------------------------------------
#
# The per-day ranked constraint list — "which constraints drive today's
# congestion". Ranked by a day-total congestion contribution ``mu_mass ·
# reach``, the day-aggregate of the ``−E_mu·SF`` decomposition node_drivers
# already uses: ``mu_mass = Σ_ts |μ[ts,c]|`` (the constraint's total
# shadow-price mass over the delivery day) times ``reach = Σ_sp |SF[c,sp]|``
# (how far that price propagates into nodal congestion). Two bases share one SF
# structure, differing only in the μ series: ``predicted`` reads the day's
# fitted E_mu from ``forecast_sf_artifact``; ``realized`` swaps in that day's
# published DAM shadow prices (``ercot_dam_shadow_prices``, joined on the same
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


# ---- /map/summary -----------------------------------------------------------


class MapSummaryResponse(BaseModel):
    """One bundled payload for the Map workspace summary (0137).

    ``topology`` is the raw settlement-point GeoJSON — the unchanged shape

    ``GET /topology`` already serves, not a typed model (topology never was
    one). ``overview`` and ``meta`` keep their own single-section
    shape and are ``null`` exactly when that section's endpoint would 503 (no
    SF window built yet / no scoreboard loaded)

    """

    topology: dict[str, Any]
    overview: MapOverview | None
    meta: MapMeta | None
    availability: dict[str, BootstrapSectionStatus]


class MapScorecardSource(BaseModel):
    """One comparison series on a map scorecard."""

    source_id: str
    series_id: Literal["model", "persistence", "oracle"]
    rank_spearman: float | None = None
    sign_agree: float | None = None
    topdecile_hit: float | None = None


class MapScorecard(BaseModel):
    """A delivery-day served grade, or one dated weekly fallback."""

    available: bool
    unavailable_reason: str | None = None
    basis: Literal["served_daily", "weekly_backtest_fallback"] | None = None
    run_id: str | None = None
    delivery_date: date
    scored_week: date | None = None
    horizon: int | None = None
    sources: list[MapScorecardSource] = []
