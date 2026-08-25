"""GET /map/* — the implied shift-factor map (spec-phase1-serve-map §3).

Serves the SF *structure* on top of Phase 0's realized-congestion node
coloring: which constraints drive which nodes (``/map/exposures``), which
nodes a constraint drives (``/map/reach``), and the de-piled all-constraint
view (``/map/overview``, each constraint drawn as a typed mark over its top
nodes). ``/map/meta`` names the refit being served. (The old
``/map/constraints`` centroid overlay was removed in 0112.)

Run + window resolution (no legacy pointer). The served run is
``settings.map_run_id``, defaulting to the newest run_id in
``sf_window_meta``; the current refit is the max ``window_start`` for that
run. Both are resolved **per request**, so a re-persist of the same run_id
is picked up without a redeploy. No ``implied_binding_proximity_current``
pointer, no ``--promote``, no ``api/ibp.py`` — that is the legacy
binding-proximity path (deleted in 0001).

Two bases, deliberately. The *click* endpoints (``/map/exposures``,
``/map/reach``) are day-indexed: they take ``t`` and serve the CT delivery day's
SF artifact — the same object ``/matrix/frame`` and ``/map/constraints/ranked``
read — so the map and the matrix agree at a given node and interval. Before 0144
they ignored ``t`` and always served the newest ``sf_window_meta`` window, which
made the DetailCard contradict the matrix on any day but the most recent.
The *aggregate* endpoints (``/map/overview``, ``/map/meta``, ``/map/summary``)
still describe one resolved ``(run_id, window_start)`` rolling refit.

``/map/exposures`` additionally chooses a *ranking* basis (0145). It defaults to
``rank=contribution`` — what actually drove the node at ``t`` — rather than the
structural ``rank=sf``, which leads with constraints that never bound and is
biased toward cells the fit merely pinned at its clip cap. Agreeing on the SF
values was never enough; the surfaces also have to agree on, and display, what
they are sorting by.

Soft-fail contract: 503 when no window is built for the resolved run (the
client renders the available pane alone); an unknown ``sp``/``constraint``
returns an empty result, not an error.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date as date_t, datetime as datetime_t
from typing import Callable, Literal, TypeVar

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg.rows import dict_row

from compute.sf_map.model.fit import SF_ABS_CAP
from compute.projection.propagate import node_contributions
from config import MAP_RUN_ID
from db import get_pool
from models import (
    ConstraintReach,
    ExposuresResponse,
    MapMeta,
    MapOverview,
    BootstrapSectionStatus, MapSummaryResponse,
    OverviewConstraint,
    RankedConstraint,
    RankedConstraints,
    ReachSp,
    SpExposure,
)
from scoreboard import get_scoreboard_headline
from services.sf_artifacts import (
    coerce_utc,
    delivery_date_for,
    load_daily_artifact,
    normalize_constraint_key,
)
from services.topology_builder import get_or_build_topology
from shared.settings import settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/map")


def _server_selected_run() -> None:
    """Keep forecast-run selection behind the server boundary for public reads."""
    return None

# In-process cache of the geocoded SP coordinates (settlement_point → (lat,
# lon)), for the /map/reach join. The CSV only changes when we re-geocode, so
# a process-lifetime cache is fine (mirrors topology_builder's source).
_SP_COORDS: dict[str, tuple[float, float]] | None = None
_SP_METADATA: dict[str, tuple[str | None, str | None]] | None = None


def _sp_coords() -> dict[str, tuple[float, float]]:
    global _SP_COORDS
    if _SP_COORDS is None:
        try:
            df = pd.read_csv(settings.settlement_points_geocoded_csv)
        except FileNotFoundError:
            log.warning("settlement_points geocoded csv missing; reach coords empty")
            _SP_COORDS = {}
            return _SP_COORDS
        df = df.dropna(subset=["lat", "lon"])
        _SP_COORDS = {
            str(r.settlement_point): (float(r.lat), float(r.lon))
            for r in df.itertuples(index=False)
        }
    return _SP_COORDS


def _sp_metadata() -> dict[str, tuple[str | None, str | None]]:
    global _SP_METADATA
    if _SP_METADATA is None:
        try:
            df = pd.read_csv(settings.settlement_points_geocoded_csv)
        except FileNotFoundError:
            log.warning("settlement_points geocoded csv missing; reach metadata empty")
            _SP_METADATA = {}
            return _SP_METADATA
        _SP_METADATA = {
            str(r.settlement_point): (
                None if pd.isna(getattr(r, 'sp_type', None)) else str(getattr(r, 'sp_type')),
                None if pd.isna(getattr(r, 'load_zone', None)) else str(getattr(r, 'load_zone')),
            )
            for r in df.itertuples(index=False)
        }
    return _SP_METADATA


def _resolve(cur) -> tuple[str, object]:
    """Resolve (run_id, window_start) for this request.

    run_id = ``settings.map_run_id`` or the newest run in ``sf_window_meta``;
    window_start = the max for that run. 503 if nothing is built.
    """
    run_id = MAP_RUN_ID
    if run_id is None:
        cur.execute(
            "SELECT run_id FROM sf_window_meta ORDER BY window_start DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(
                status_code=503,
                detail="no SF run is built yet (sf_window_meta is empty).",
            )
        run_id = row["run_id"]

    cur.execute(
        "SELECT max(window_start) AS ws FROM sf_window_meta WHERE run_id = %s",
        (run_id,),
    )
    row = cur.fetchone()
    if row is None or row["ws"] is None:
        raise HTTPException(
            status_code=503,
            detail=f"no window built for run_id={run_id}.",
        )
    return run_id, row["ws"]


def _meta_row(cur, run_id: str, window_start) -> dict:
    cur.execute(
        "SELECT run_id, window_start, window_end, fit_r2, oos_r2, coverage, "
        "sf_stability, n_kept FROM sf_window_meta "
        "WHERE run_id = %s AND window_start = %s",
        (run_id, window_start),
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(
            status_code=503,
            detail=f"window {window_start} missing from sf_window_meta for {run_id}.",
        )
    return row


def _forecast_run_id(cur) -> str:
    """The promoted forecast run — the artifact namespace, not the map's."""
    cur.execute("SELECT run_id FROM forecast_current WHERE layer = 'ercot'")
    row = cur.fetchone()
    if row is None:
        raise HTTPException(status_code=503, detail="no forecast run is published yet.")
    return str(row["run_id"])


def _latest_artifact_day(cur, run_id: str):
    cur.execute(
        "SELECT max(delivery_date) AS d FROM forecast_sf_artifact WHERE run_id = %s",
        (run_id,),
    )
    row = cur.fetchone()
    return None if row is None else row["d"]


def _nearest_past_artifact_day(cur, run_id: str, day):
    """The newest built delivery day at or before ``day``.

    The fallback the constraint reach serves when the requested day itself has no
    artifact (a lagging or failed forecast job, or a forward day). SF is
    topology-driven and drifts slowly, so the nearest earlier build is a faithful
    stand-in for "who this constraint drives" rather than an empty card. ``None``
    when nothing was built that early (a date before the artifact history).
    """
    if day is None:
        return None
    cur.execute(
        "SELECT max(delivery_date) AS d FROM forecast_sf_artifact "
        "WHERE run_id = %s AND delivery_date <= %s",
        (run_id, day),
    )
    row = cur.fetchone()
    return None if row is None else row["d"]


def _click_artifact(cur, t: datetime_t | None):
    """Resolve (run_id, delivery_date, artifact) for a node/constraint click.

    ``t`` is an instant on the map's scrubber; the artifact partition is its CT
    delivery day (0133 blocks, cut in ``delivery_date_for`` — never a UTC date,
    which is what blanked the matrix's evening hours in 0143.1). ``t`` omitted
    falls back to the run's latest built day.

    Returns ``artifact=None`` when the day has no artifact; callers turn that
    into an explicit unavailable response rather than silently substituting a
    rolling-window fit from a different basis (0144).
    """
    run_id = _forecast_run_id(cur)
    day = delivery_date_for(t) if t is not None else _latest_artifact_day(cur, run_id)
    if day is None:
        return run_id, None, None
    return run_id, day, load_daily_artifact(cur, run_id, day)


def _interval_in_artifact(artifact, t: datetime_t | None) -> bool:
    """Whether the block actually covers the requested instant.

    A correctly cut CT block covers all 24 hours of its delivery day, so this is
    always true on well-formed data. It matters when a block is misaligned or
    partial: /matrix/frame rejects such an hour with ``interval_not_in_artifact``,
    and the map must reach the same verdict rather than answering from the day's
    SF while the matrix reports nothing there — a map/matrix disagreement is the
    exact defect 0144 exists to remove.
    """
    return t is None or pd.Timestamp(coerce_utc(t)) in artifact.E_mu.index


def _artifact_window(artifact) -> tuple[datetime_t, datetime_t]:
    """The day block's own bounds — what this response's SF actually describes."""
    idx = artifact.E_mu.index
    return idx.min().to_pydatetime(), idx.max().to_pydatetime()


def _hour_mu(artifact, t: datetime_t | None) -> pd.Series:
    """The day's forecast μ vector at one interval, or summed over the block.

    A node card answers "what drove this node *now*", so the default is the
    single scrubber hour. With ``t`` omitted there is no hour to stand on and
    the whole block is summed, which is the same roll-up ``/analysis/node``
    performs when its ``hours`` filter is absent.
    """
    if t is None:
        return artifact.E_mu.sum(axis=0)
    return artifact.E_mu.loc[pd.Timestamp(coerce_utc(t))]


def _is_clipped(sf: float) -> bool:
    """Whether the fit pinned this cell at its ``|SF|`` cap.

    ``compute/sf/fit.py`` clips to exactly ``±SF_ABS_CAP``, so equality with the
    cap is an exact test — no per-cell mask needs persisting (the fit's
    ``n_clipped`` is only a count, and is dropped before serving).
    """
    return abs(sf) >= SF_ABS_CAP


def _geo_metadata(cur, constraint_keys: list[str]) -> dict[str, dict]:
    """Best-effort structural metadata, newest window (matrix._constraint_types).

    ``ctype``/``n_rail``/``peak_offrail`` describe a constraint's shape, not one
    day's SF, so they stay on ``constraint_geo``; the day-specific magnitudes
    (``max_abs_sf``, ``binding_hours``) come from the artifact instead.
    """
    if not constraint_keys:
        return {}
    cur.execute(
        "SELECT DISTINCT ON (constraint_key) constraint_key, ctype, n_rail, peak_offrail "
        "FROM constraint_geo WHERE constraint_key = ANY(%s) "
        "ORDER BY constraint_key, window_start DESC",
        (constraint_keys,),
    )
    return {str(r["constraint_key"]): r for r in cur.fetchall()}


@router.get("/meta", response_model=MapMeta, summary="The refit the map is serving")
def get_map_meta() -> MapMeta:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, window_start = _resolve(cur)
        return MapMeta(**_meta_row(cur, run_id, window_start))


def _absent_sp_reason(cur, run_id: str, day, sp: str) -> str:
    """Why a node has no SF on this day: not in service, or just not fitted.

    The run's own nodal forecast is the existence test — a node ERCOT had not
    commissioned yet has no rows there either, while one merely dropped by the
    fit does. ``day_rows`` guards a day the run never forecast at all, where the
    two are indistinguishable. One indexed count, only on this branch.
    """
    cur.execute(
        "SELECT count(*) FILTER (WHERE settlement_point = %s) AS sp_rows, "
        "count(*) AS day_rows FROM forecast_nodal "
        "WHERE run_id = %s AND delivery_date = %s",
        (sp, run_id, day),
    )
    row = cur.fetchone() or {}
    if row.get("day_rows") and not row.get("sp_rows"):
        return "sp_not_in_service"
    return "sp_not_in_fit"


@router.get(
    "/exposures",
    response_model=ExposuresResponse,
    summary="Top-k constraints driving a node (node-explorer click)",
)
def get_map_exposures(
    sp: str = Query(..., description="Settlement point to explain"),
    k: int = Query(15, ge=1, le=500, description="Number of top constraints"),
    t: datetime_t | None = Query(
        None,
        description="Delivery interval in ISO-8601 UTC. The SF served is the CT "
        "delivery day's artifact, so this matches /matrix/frame at the same "
        "node and interval. Omit for the run's latest built day.",
    ),
    rank: Literal["contribution", "sf"] = Query(
        "contribution",
        description="Ordering basis. 'contribution' (default) ranks what actually "
        "drove the node at t, by |-SF x mu|, dropping constraints that did not "
        "bind. 'sf' ranks structural exposure by |SF| over every constraint in "
        "the day's fit, including quiet ones.",
    ),
) -> ExposuresResponse:
    """Rank a node's constraints by what drove it, or by structural exposure.

    The two bases read identical SF values and differ only in ordering and
    filtering, which is precisely why they looked like a data disagreement
    (0145): under ``sf`` this card led with constraints whose μ was zero all day
    — including cells merely pinned at the fit's clip cap — while the constraint
    carrying most of the node's actual congestion ranked below them. Clients
    should say which basis is on screen.
    """
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, day, artifact = _click_artifact(cur, t)
        if artifact is None:
            return ExposuresResponse(
                sp=sp, run_id=run_id, window_start=t, window_end=t, k=k,
                rank=rank, available=False, unavailable_reason="artifact_missing",
                exposures=[],
            )

        window_start, window_end = _artifact_window(artifact)
        if not _interval_in_artifact(artifact, t):
            return ExposuresResponse(
                sp=sp, run_id=run_id, window_start=window_start,
                window_end=window_end, k=k, rank=rank, available=False,
                unavailable_reason="interval_not_in_artifact", exposures=[],
            )
        if sp not in artifact.SF.columns:
            # Its own reason: an empty list would read as "in the fit, bound
            # nothing" (0146). Pins come from the static geocoded CSV, which has
            # no per-day universe, so any node is clickable on any day.
            return ExposuresResponse(
                sp=sp, run_id=run_id, window_start=window_start,
                window_end=window_end, k=k, rank=rank, available=False,
                unavailable_reason=_absent_sp_reason(cur, run_id, day, sp),
                exposures=[],
            )

        column = artifact.SF[sp]
        # Stable, unsigned headline (spec §6): max_c |SF[sp,c]| over ALL
        # constraints, independent of k and of the ranking basis.
        node_max = float(column.abs().max())

        node_gross_total = None
        if rank == "contribution":
            mu = _hour_mu(artifact, t).reindex(artifact.SF.index).fillna(0.0)
            # Shared with /analysis/node so the two cannot drift: the map card
            # and the node analysis must be the same decomposition.
            contributions = node_contributions(artifact, sp, mu)
            # Dropped, not sorted last: a constraint that did not bind
            # contributed nothing, and listing it as a "driver" is the defect.
            contributions = contributions[contributions != 0.0]
            # A signed-net denominator makes a row's apparent "share" explode
            # when constraints offset. Serve the full gross driver magnitude
            # for a bounded, cancellation-safe UI share.
            node_gross_total = float(contributions.abs().sum())
            ordered = contributions.abs().sort_values(ascending=False).index[:k]
        else:
            mu = None
            contributions = None
            ordered = column.abs().sort_values(ascending=False).index[:k]

        geo = _geo_metadata(cur, [str(key) for key in ordered])
        exposures = [
            SpExposure(
                constraint_key=str(key),
                ctype=(geo.get(str(key)) or {}).get("ctype"),
                sf=float(column.loc[key]),
                sf_clipped=_is_clipped(float(column.loc[key])),
                mu=None if mu is None else float(mu.loc[key]),
                contribution=None if contributions is None else float(contributions.loc[key]),
                # Day-specific magnitudes come from the artifact, matching what
                # /matrix/frame reports for the same constraint on the same day.
                max_abs_sf=float(artifact.SF.loc[key].abs().max()),
                binding_hours=int((artifact.E_mu[key].abs() > 0).sum()),
            )
            for key in ordered
        ]

    return ExposuresResponse(
        sp=sp,
        run_id=run_id,
        window_start=window_start,
        window_end=window_end,
        k=k,
        rank=rank,
        node_max_abs_sf=node_max,
        node_gross_total=node_gross_total,
        exposures=exposures,
    )


@router.get(
    "/reach",
    response_model=ConstraintReach,
    summary="Top-k nodes a constraint drives (constraint click)",
)
def get_map_reach(
    constraint: str = Query(..., description="Constraint key to trace"),
    k: int = Query(15, ge=1, le=500, description="Number of top nodes"),
    t: datetime_t | None = Query(
        None,
        description="Delivery interval in ISO-8601 UTC. The SF served is the CT "
        "delivery day's artifact, so this matches /matrix/frame at the same "
        "constraint and interval. Omit for the run's latest built day.",
    ),
    full: bool = Query(
        False,
        description="Ignore k and return every node above min_frac — the "
        "unbounded reach the matrix Read pane needs (plan/0139-0001), not a "
        "display top-k. k stays the map/brief click's own knob.",
    ),
    min_frac: float = Query(
        0.05, ge=0.0, le=1.0,
        description="Noise floor: drop nodes whose |SF| is below this fraction "
        "of the constraint's peak |SF|. Without it, top-k pads a weakly-fit "
        "constraint (few real nodes) with noise-floor entries.",
    ),
    abs_floor: float = Query(
        0.0, ge=0.0, le=1.0,
        description="Absolute |SF| floor, combined with min_frac as "
        "max(min_frac*peak, abs_floor). The relative floor follows each "
        "constraint's shape but is meaningless for a noise-peak constraint "
        "(peak ~0.01 lets its whole tail through); this cuts that off. The map "
        "passes ~0.03. Default 0 preserves the matrix Read pane's complete reach.",
    ),
) -> ConstraintReach:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, day, artifact = _click_artifact(cur, t)
        basis = "artifact"
        if artifact is None:
            # The requested delivery day has no artifact. Which nodes a constraint
            # drives is structural (topology-driven, slow to drift), so fall back to
            # the nearest EARLIER built day rather than blanking the card — a
            # resilience net for a lagging or failed forecast job. Only whole-day
            # absence falls back; a constraint missing from a day that DOES have an
            # artifact still reads as "didn't bind that day" below, not a stale
            # substitute. window_start/window_end + basis report the day served.
            fallback_day = _nearest_past_artifact_day(cur, run_id, day)
            if fallback_day is not None:
                artifact = load_daily_artifact(cur, run_id, fallback_day)
                day, basis = fallback_day, "nearest_past"
            if artifact is None:
                return ConstraintReach(
                    constraint_key=constraint, run_id=run_id,
                    window_start=t, window_end=t, k=k,
                    available=False, unavailable_reason="artifact_missing", sps=[],
                )

        window_start, window_end = _artifact_window(artifact)
        geo = (_geo_metadata(cur, [constraint]).get(constraint) or {})
        # A nearest-past fallback is served precisely because `t` is not in any
        # built block, so the interval gate only applies to the day's own artifact.
        if basis == "artifact" and not _interval_in_artifact(artifact, t):
            return ConstraintReach(
                constraint_key=constraint, ctype=geo.get("ctype"), run_id=run_id,
                window_start=window_start, window_end=window_end, k=k,
                n_rail=geo.get("n_rail"), peak_offrail=geo.get("peak_offrail"),
                available=False, unavailable_reason="interval_not_in_artifact",
                sps=[],
            )
        if constraint not in artifact.SF.index:
            return ConstraintReach(
                constraint_key=constraint, ctype=geo.get("ctype"), run_id=run_id,
                window_start=window_start, window_end=window_end, k=k,
                n_rail=geo.get("n_rail"), peak_offrail=geo.get("peak_offrail"),
                available=False, unavailable_reason="constraint_not_in_artifact",
                sps=[],
            )

        row = artifact.SF.loc[constraint]
        # Day-specific magnitudes from the artifact; the geo row keeps only the
        # structural shape fields, which are not per-day (0144).
        max_abs_sf = float(row.abs().max())
        binding_hours = int((artifact.E_mu[constraint].abs() > 0).sum())
        # This is the forecast μ that belongs to the selected cursor interval.
        # A nearest-past SF fallback remains structural only: its E_mu describes
        # another day, so never present it as the selected hour's shadow price.
        shadow_price = (
            float(artifact.E_mu.loc[pd.Timestamp(coerce_utc(t)), constraint])
            if t is not None and basis == "artifact"
            else None
        )
        dam_mu = None
        if t is not None and basis == "artifact":
            cur.execute(
                "SELECT DISTINCT ON (interval_ts, constraint_name, contingency_name) shadow_price "
                "FROM ercot_dam_shadow_prices "
                "WHERE interval_ts = %s "
                "AND btrim(constraint_name) || '|' || btrim(contingency_name) = %s "
                "ORDER BY interval_ts, constraint_name, contingency_name, dst_flag ASC",
                (pd.Timestamp(coerce_utc(t)).to_pydatetime(), constraint),
            )
            dam_row = cur.fetchone()
            if dam_row is not None and dam_row["shadow_price"] is not None:
                dam_mu = float(dam_row["shadow_price"])
        daily_mass = artifact.E_mu.abs().sum(axis=0)
        daily_rank = int(daily_mass.sort_values(ascending=False, kind="stable").index.get_loc(constraint)) + 1

        # Magnitude floor relative to the constraint's own peak |SF|, combined
        # with an absolute floor. The relative floor follows the constraint's
        # shape; the absolute floor stops a noise-peak constraint (peak ~0.01)
        # from admitting its whole tail. A weakly identified constraint has almost
        # no structure past a few nodes, so top-k alone scrapes the noise floor.
        floor = max(min_frac * max_abs_sf if max_abs_sf else 0.0, abs_floor)
        above = row[row.abs() >= floor]
        ranked = above.reindex(above.abs().sort_values(ascending=False).index)

        if full:
            # No limit at all: a dev-DB audit (plan/0139-0001) found ~half the
            # constraint universe has real reach past 500 nodes at even a
            # 5%-of-peak floor, so any fixed k is a guess that can go stale as
            # the node universe grows. truncated is always False here — full
            # means complete by construction, bounded only by min_frac.
            truncated = False
        else:
            truncated = len(ranked) > k
            ranked = ranked.iloc[:k]

        coords = _sp_coords()
        metadata = _sp_metadata()
        sps = []
        for name, sf in ranked.items():
            lat, lon = coords.get(str(name), (None, None))
            settlement_point_type, load_zone = metadata.get(str(name), (None, None))
            sps.append(ReachSp(settlement_point=str(name),
                               sf=float(sf), lat=lat, lon=lon,
                               settlement_point_type=settlement_point_type,
                               load_zone=load_zone))

    return ConstraintReach(
        constraint_key=constraint,
        ctype=geo.get("ctype"),
        run_id=run_id,
        window_start=window_start,
        window_end=window_end,
        k=k,
        max_abs_sf=max_abs_sf,
        n_rail=geo.get("n_rail"),
        peak_offrail=geo.get("peak_offrail"),
        binding_hours=binding_hours,
        shadow_price=shadow_price,
        dam_mu=dam_mu,
        forecast_error=None if shadow_price is None or dam_mu is None else shadow_price - dam_mu,
        daily_mu_rank=daily_rank,
        daily_mu_sum=float(daily_mass.loc[constraint]),
        import_members=int((row < 0.0).sum()),
        export_members=int((row > 0.0).sum()),
        available=bool(sps),
        basis=basis,
        truncated=truncated,
        sps=sps,
    )


@router.get(
    "/overview",
    response_model=MapOverview,
    summary="De-piled overview: top-n constraints at their |SF|² cores",
)
def get_map_overview(
    n: int = Query(70, ge=1, le=500,
                   description="Number of top constraints by binding hours."),
    k: int = Query(16, ge=1, le=100,
                   description="Top signed nodes per constraint (the mark's field)."),
    min_frac: float = Query(
        0.15, ge=0.0, le=1.0,
        description="Noise floor: drop a constraint's nodes whose |SF| is below "
        "this fraction of its peak |SF|, so a weakly-fit constraint's mark is its "
        "real nodes, not the noise floor. Peak is constraint_geo.max_abs_sf.",
    ),
) -> MapOverview:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, window_start = _resolve(cur)
        meta = _meta_row(cur, run_id, window_start)

        # The n heaviest constraints this window — the overview set. NULLS LAST so
        # unlocatable ones don't crowd out located ones at the top.
        cur.execute(
            "SELECT constraint_key, ctype, binding_hours, max_abs_sf "
            "FROM constraint_geo "
            "WHERE run_id = %s AND window_start = %s "
            "ORDER BY binding_hours DESC NULLS LAST LIMIT %s",
            (run_id, window_start, n),
        )
        rows = cur.fetchall()
        keys = [r["constraint_key"] for r in rows]

        # All nodes for those constraints in one indexed slice, ordered so the
        # per-constraint top-k is a running head in Python. The magnitude floor is
        # per-constraint (relative to each one's peak), so it's applied here, not
        # in SQL. ANY(%s) keeps it to a single round-trip regardless of n.
        by_key: dict[str, list[ReachSp]] = {key: [] for key in keys}
        if keys:
            cur.execute(
                "SELECT constraint_key, settlement_point, sf "
                "FROM implied_shift_factors "
                "WHERE run_id = %s AND window_start = %s "
                "AND constraint_key = ANY(%s) "
                "ORDER BY constraint_key, abs(sf) DESC",
                (run_id, window_start, keys),
            )
            coords = _sp_coords()
            metadata = _sp_metadata()
            floors = {r["constraint_key"]: (min_frac * r["max_abs_sf"])
                      if r["max_abs_sf"] else 0.0 for r in rows}
            for r in cur.fetchall():
                bucket = by_key[r["constraint_key"]]
                if len(bucket) >= k or abs(r["sf"]) < floors[r["constraint_key"]]:
                    continue
                lat, lon = coords.get(r["settlement_point"], (None, None))
                settlement_point_type, load_zone = metadata.get(r["settlement_point"], (None, None))
                bucket.append(ReachSp(settlement_point=r["settlement_point"],
                                      sf=r["sf"], lat=lat, lon=lon,
                                      settlement_point_type=settlement_point_type,
                                      load_zone=load_zone))

        constraints = [
            OverviewConstraint(
                constraint_key=r["constraint_key"],
                ctype=r["ctype"],
                binding_hours=r["binding_hours"],
                max_abs_sf=r["max_abs_sf"],
                nodes=by_key[r["constraint_key"]],
            )
            for r in rows
        ]

    return MapOverview(
        run_id=run_id,
        window_start=meta["window_start"],
        window_end=meta["window_end"],
        n=n,
        k=k,
        oos_r2=meta["oos_r2"],
        sf_stability=meta["sf_stability"],
        constraints=constraints,
    )


def _realized_mu_summary(cur, lo, hi) -> dict[str, tuple[float, int]]:
    """Daily realized μ summaries keyed to the artifact constraint vocabulary.

    The bounded DAM window is the artifact's own interval range, so predicted
    and realized summaries describe the same delivery-day basis. Each value is
    ``(Σ|μ|, binding-hour count)``.
    """
    cur.execute(
        "SELECT constraint_name, contingency_name, sum(abs(shadow_price)) AS mass, "
        "count(*) FILTER (WHERE abs(shadow_price) > 0) AS binding_hours "
        "FROM ercot_dam_shadow_prices "
        "WHERE interval_ts >= %s AND interval_ts <= %s AND shadow_price IS NOT NULL "
        "GROUP BY constraint_name, contingency_name",
        (lo, hi),
    )
    return {
        normalize_constraint_key(r["constraint_name"], r["contingency_name"]): (
            float(r["mass"]),
            int(r["binding_hours"]),
        )
        for r in cur.fetchall()
        if r["mass"] is not None
    }


@router.get(
    "/constraints/ranked",
    response_model=RankedConstraints,
    summary="Per-day ranked constraints by congestion contribution",
)
def get_map_constraints_ranked(
    day: date_t | None = Query(
        None,
        description="Delivery date to rank. Omit for the forecast run's latest "
        "day with a built SF+μ artifact.",
    ),
    basis: str = Query(
        "predicted",
        pattern="^(predicted|realized)$",
        description="μ series: predicted (the day's fitted E_mu) or realized "
        "(that day's published DAM shadow prices). SF structure is shared.",
    ),
    run_id: str | None = Depends(_server_selected_run),
    k: int = Query(30, ge=1, le=200, description="Top-k constraints to return."),
    min_frac: float = Query(
        0.05, ge=0.0, le=1.0,
        description="Noise floor: a node counts toward a constraint's members / "
        "lobes only if its |SF| is at least this fraction of the constraint's "
        "peak |SF| (mirrors /map/reach).",
    ),
) -> RankedConstraints:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        # Resolve the forecast run (this feature's own pointer, not the SF-map
        # run) and the delivery day, then load that day's SF+μ blob.
        if run_id is None:
            cur.execute("SELECT run_id FROM forecast_current WHERE layer = 'ercot'")
            row = cur.fetchone()
            if row is None:
                raise HTTPException(
                    status_code=503,
                    detail="no forecast run is published yet (forecast_current is empty).",
                )
            run_id = row["run_id"]

        if day is None:
            cur.execute(
                "SELECT max(delivery_date) AS d FROM forecast_sf_artifact WHERE run_id = %s",
                (run_id,),
            )
            row = cur.fetchone()
            if row is None or row["d"] is None:
                raise HTTPException(
                    status_code=503,
                    detail=f"no SF+μ artifact built for run_id={run_id}.",
                )
            day = row["d"]

        assert run_id is not None and day is not None  # resolved-or-503 above
        art = load_daily_artifact(cur, run_id, day)
        if art is None:
            raise HTTPException(
                status_code=503,
                detail=f"no SF+μ artifact for run_id={run_id} on {day}.",
            )

        # Daily μ summaries for the chosen basis, on the artifact's shared
        # constraint-key index. Predicted reads fitted E_mu; realized swaps in
        # bounded DAM shadow prices over the same hours.
        keys = art.SF.index
        if basis == "realized":
            lo, hi = art.E_mu.index.min(), art.E_mu.index.max()
            realized = _realized_mu_summary(cur, lo.to_pydatetime(), hi.to_pydatetime())
            realized_summary = pd.DataFrame.from_dict(
                realized,
                orient="index",
                columns=["mu_mass", "binding_hours"],
            )
            mu_mass = realized_summary.get("mu_mass", pd.Series(dtype=float)).reindex(keys).fillna(0.0)
            binding_hours = realized_summary.get("binding_hours", pd.Series(dtype=float)).reindex(keys).fillna(0).astype(int)
        else:
            abs_mu = art.E_mu.abs().reindex(columns=keys, fill_value=0.0)
            mu_mass = abs_mu.sum(axis=0)
            binding_hours = (abs_mu > 0.0).sum(axis=0).astype(int)

        # reach = Σ_sp |SF|; contribution = mu_mass · reach (the day-total of the
        # −E_mu·SF nodal decomposition), ranked descending.
        reach = art.SF.abs().sum(axis=1)
        contribution = (mu_mass * reach).astype(float)
        ranked = contribution[contribution > 0.0].sort_values(ascending=False)
        top_keys = list(ranked.index[:k])

        # ctype for the top keys, from the SF-map's constraint_geo (the same source
        # the overlay marks take their type from), so a panel row and its overlay
        # mark share a key and a type. Best-effort: unmatched keys → null.
        geo: dict[str, dict] = {}
        if top_keys:
            m_run, m_ws = _resolve(cur)
            cur.execute(
                "SELECT constraint_key, ctype FROM constraint_geo "
                "WHERE run_id = %s AND window_start = %s AND constraint_key = ANY(%s)",
                (m_run, m_ws, top_keys),
            )
            geo = {r["constraint_key"]: r for r in cur.fetchall()}

    coords = _sp_coords()
    out: list[RankedConstraint] = []
    for i, key in enumerate(top_keys):
        sf_row = art.SF.loc[key]
        peak_abs = float(sf_row.abs().max())
        floor = min_frac * peak_abs if peak_abs else 0.0
        src: list[tuple[float, float, float]] = []
        snk: list[tuple[float, float, float]] = []
        for sp, sf in sf_row.items():
            sf = float(sf)
            if abs(sf) < floor or sf == 0.0:
                continue
            latlon = coords.get(str(sp))
            if latlon is None:
                continue
            (snk if sf > 0 else src).append((sf, latlon[0], latlon[1]))
        g = geo.get(key, {})
        out.append(
            RankedConstraint(
                constraint_id=key,
                rank=i + 1,
                congestion_contribution=float(ranked.loc[key]),
                mu_mass=float(mu_mass.loc[key]),
                binding_hours=int(binding_hours.loc[key]),
                reach=float(reach.loc[key]),
                n_members=len(src) + len(snk),
                ctype=g.get("ctype"),
                n_import=len(src),
                n_export=len(snk),
            )
        )

    return RankedConstraints(
        run_id=run_id,
        delivery_date=day,
        basis=basis,
        k=k,
        n_ranked=int((contribution > 0.0).sum()),
        constraints=out,
    )


# --------------------------------------------------------------------------
# /map/summary — the Map workspace's load-time quartet in one call (0137)
# --------------------------------------------------------------------------

_T = TypeVar("_T")


def _soft_fail(build: Callable[[], _T]) -> _T | None:
    """Run one section's builder; a 503 (nothing built/loaded for it yet)
    becomes ``None`` here instead of failing the whole bundle — the same
    soft-fail the client already applies per single-section endpoint."""
    try:
        return build()
    except HTTPException as exc:
        if exc.status_code == 503:
            return None
        raise


def _bootstrap_status(section: object | None) -> BootstrapSectionStatus:
    """Describe a bundled section without making its null payload ambiguous."""
    if section is None:
        return BootstrapSectionStatus(available=False, unavailable_reason="source_unavailable")
    return BootstrapSectionStatus(
        available=True,
        run_id=getattr(section, "run_id", None),
        delivery_date=getattr(section, "delivery_date", None),
        horizon=getattr(section, "horizon", None),
    )


@router.get(
    "/summary",
    response_model=MapSummaryResponse,
    summary="One bundled payload for the Map workspace summary (0137)",
)
def get_map_summary() -> MapSummaryResponse:
    """Compose the Map workspace's four load-time requests behind one call.

    ``overview``/``meta`` resolve the same SF map run+window
    (``_resolve()``'s own logic, unchanged); ``headline`` reads the separate
    backtest board. None of the three is forced onto a shared value — that
    matches what today's three independent requests already do. Params match
    exactly what ``MapWorkspace.tsx`` requests today: overview at
    ``n=70, k=6`` (its own override of the single-section endpoint's default
    ``k=16``), headline at the default regime.

    Each handler is called directly as a plain function, bypassing FastAPI's
    request-time dependency injection, so every parameter is passed an
    explicit literal (see ``get_brief_day``'s docstring for why). Interaction
    endpoints (``/map/reach``, ``/map/exposures``, ``/map/constraints/ranked``)
    are untouched — they fire on hover/click/navigation, not load.

    Topology, being both the largest and the least likely to fail, runs
    synchronously on this thread while the other three run on a pool — a free
    fourth concurrent path without a fourth pool slot.
    """
    with ThreadPoolExecutor(max_workers=3) as pool:
        overview = pool.submit(_soft_fail, lambda: get_map_overview(70, 6, 0.15))
        meta = pool.submit(_soft_fail, get_map_meta)
        headline = pool.submit(_soft_fail, lambda: get_scoreboard_headline(None, "all"))
        topology = get_or_build_topology()
        overview_result = overview.result()
        meta_result = meta.result()
        headline_result = headline.result()
        return MapSummaryResponse(
            topology=topology,
            overview=overview_result,
            meta=meta_result,
            headline=headline_result,
            availability={
                "topology": BootstrapSectionStatus(available=True),
                "overview": _bootstrap_status(overview_result),
                "meta": _bootstrap_status(meta_result),
                "headline": _bootstrap_status(headline_result),
            },
        )
