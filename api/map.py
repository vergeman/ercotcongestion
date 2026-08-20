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

Soft-fail contract: 503 when no window is built for the resolved run (the
client renders the available pane alone); an unknown ``sp``/``constraint``
returns an empty result, not an error.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date as date_t, datetime as datetime_t
from typing import Callable, TypeVar

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from config import MAP_RUN_ID
from db import get_pool
from models import (
    ConstraintReach,
    ExposuresResponse,
    MapMeta,
    MapOverview,
    MapSummaryResponse,
    OverviewConstraint,
    RankedConstraint,
    RankedConstraints,
    ReachSp,
    SpExposure,
)
from scoreboard import get_scoreboard_headline
from services.sf_artifacts import (
    delivery_date_for,
    load_daily_artifact,
    normalize_constraint_key,
)
from services.topology_builder import get_or_build_topology
from shared.settings import settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/map")

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


def _artifact_window(artifact) -> tuple[datetime_t, datetime_t]:
    """The day block's own bounds — what this response's SF actually describes."""
    idx = artifact.E_mu.index
    return idx.min().to_pydatetime(), idx.max().to_pydatetime()


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
) -> ExposuresResponse:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, day, artifact = _click_artifact(cur, t)
        if artifact is None:
            return ExposuresResponse(
                sp=sp, run_id=run_id, window_start=t, window_end=t, k=k,
                available=False, unavailable_reason="artifact_missing",
                exposures=[],
            )

        window_start, window_end = _artifact_window(artifact)
        if sp not in artifact.SF.columns:
            # A located node absent from this day's fit: available, empty — the
            # same soft-fail an unknown sp always had.
            return ExposuresResponse(
                sp=sp, run_id=run_id, window_start=window_start,
                window_end=window_end, k=k, exposures=[],
            )

        column = artifact.SF[sp]
        # Stable, unsigned headline (spec §6): max_c |SF[sp,c]| over ALL
        # constraints, independent of k.
        node_max = float(column.abs().max())
        top = column.reindex(column.abs().sort_values(ascending=False).index[:k])

        geo = _geo_metadata(cur, [str(key) for key in top.index])
        exposures = [
            SpExposure(
                constraint_key=str(key),
                ctype=(geo.get(str(key)) or {}).get("ctype"),
                sf=float(sf),
                # Day-specific magnitudes come from the artifact, matching what
                # /matrix/frame reports for the same constraint on the same day.
                max_abs_sf=float(artifact.SF.loc[key].abs().max()),
                binding_hours=int((artifact.E_mu[key].abs() > 0).sum()),
            )
            for key, sf in top.items()
        ]

    return ExposuresResponse(
        sp=sp,
        run_id=run_id,
        window_start=window_start,
        window_end=window_end,
        k=k,
        node_max_abs_sf=node_max,
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
) -> ConstraintReach:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, day, artifact = _click_artifact(cur, t)
        if artifact is None:
            return ConstraintReach(
                constraint_key=constraint, run_id=run_id,
                window_start=t, window_end=t, k=k,
                available=False, unavailable_reason="artifact_missing", sps=[],
            )

        window_start, window_end = _artifact_window(artifact)
        geo = (_geo_metadata(cur, [constraint]).get(constraint) or {})
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

        # Magnitude floor relative to the constraint's own peak |SF|. A weakly
        # identified constraint has almost no structure past a few nodes, so
        # top-k alone scrapes the noise floor; drop |SF| < min_frac * peak.
        floor = min_frac * max_abs_sf if max_abs_sf else 0.0
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
        available=bool(sps),
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


def _realized_mu_mass(cur, lo, hi) -> dict[str, float]:
    """Σ |shadow_price| over the delivery day per ``constraint_name|contingency_name``
    — the realized-basis μ series, keyed the same way the SF panel is (compute.sf
    .panels), so it aligns to the artifact's constraint index with no name match."""
    cur.execute(
        "SELECT constraint_name, contingency_name, sum(abs(shadow_price)) AS mass "
        "FROM ercot_dam_shadow_prices "
        "WHERE interval_ts >= %s AND interval_ts <= %s AND shadow_price IS NOT NULL "
        "GROUP BY constraint_name, contingency_name",
        (lo, hi),
    )
    return {
        normalize_constraint_key(r["constraint_name"], r["contingency_name"]): float(r["mass"])
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
    run_id: str | None = Query(
        None,
        description="Forecast model version. Omit for the current promoted run "
        "(forecast_current[ercot]).",
    ),
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

        # μ mass per constraint (Σ_ts |μ|) for the chosen basis, on the artifact's
        # shared constraint-key index. Predicted reads the fitted E_mu; realized
        # swaps in the day's DAM shadow prices over the same hours.
        keys = art.SF.index
        if basis == "realized":
            lo, hi = art.E_mu.index.min(), art.E_mu.index.max()
            realized = _realized_mu_mass(cur, lo.to_pydatetime(), hi.to_pydatetime())
            mu_mass = pd.Series(realized, dtype=float).reindex(keys).fillna(0.0)
        else:
            mu_mass = art.E_mu.abs().sum(axis=0).reindex(keys).fillna(0.0)

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
        return MapSummaryResponse(
            topology=topology,
            overview=overview.result(),
            meta=meta.result(),
            headline=headline.result(),
        )
