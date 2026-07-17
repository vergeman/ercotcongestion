"""GET /map/* — the implied shift-factor map (spec-phase1-serve-map §3).

Serves the SF *structure* on top of Phase 0's realized-congestion node
coloring: which constraints drive which nodes (``/map/exposures``), which
nodes a constraint drives (``/map/reach``), and where each constraint lives
(``/map/constraints``, the |SF|-weighted centroid overlay). ``/map/meta``
names the refit being served.

Run + window resolution (no legacy pointer). The served run is
``settings.map_run_id``, defaulting to the newest run_id in
``sf_window_meta``; the current refit is the max ``window_start`` for that
run. Both are resolved **per request**, so a re-persist of the same run_id
is picked up without a redeploy. No ``implied_binding_proximity_current``
pointer, no ``--promote``, no ``api/ibp.py`` — that is the legacy
binding-proximity path (deleted in 0001).

Not time-indexed: the SF structure is fixed per refit, so every response
describes one resolved ``(run_id, window_start)``, not an hour. Queries are
indexed slices (``WHERE run_id=? AND window_start=? AND settlement_point=?
ORDER BY abs(sf) DESC LIMIT k`` and its transpose) — sub-ms.

Soft-fail contract: 503 when no window is built for the resolved run (the
client renders the available pane alone); an unknown ``sp``/``constraint``
returns an empty result, not an error.
"""
from __future__ import annotations

import logging

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from config import MAP_RUN_ID
from db import get_pool
from models import (
    ConstraintGeo,
    ConstraintReach,
    ExposuresResponse,
    MapMeta,
    MapOverview,
    OverviewConstraint,
    ReachSp,
    SpExposure,
)
from shared.settings import settings

log = logging.getLogger(__name__)

router = APIRouter(prefix="/map")

# In-process cache of the geocoded SP coordinates (settlement_point → (lat,
# lon)), for the /map/reach join. The CSV only changes when we re-geocode, so
# a process-lifetime cache is fine (mirrors topology_builder's source).
_SP_COORDS: dict[str, tuple[float, float]] | None = None


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


@router.get("/meta", response_model=MapMeta, summary="The refit the map is serving")
def get_map_meta() -> MapMeta:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, window_start = _resolve(cur)
        return MapMeta(**_meta_row(cur, run_id, window_start))


@router.get(
    "/constraints",
    response_model=list[ConstraintGeo],
    summary="Constraint overlay for the current refit",
)
def get_map_constraints() -> list[ConstraintGeo]:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, window_start = _resolve(cur)
        cur.execute(
            "SELECT constraint_key, lat, lon, zone_shares, kv_mean, kv_max, "
            "spread_km, max_abs_sf, n_rail, peak_offrail, binding_hours "
            "FROM constraint_geo "
            "WHERE run_id = %s AND window_start = %s "
            "ORDER BY max_abs_sf DESC NULLS LAST",
            (run_id, window_start),
        )
        return [ConstraintGeo(**r) for r in cur.fetchall()]


@router.get(
    "/exposures",
    response_model=ExposuresResponse,
    summary="Top-k constraints driving a node (node-explorer click)",
)
def get_map_exposures(
    sp: str = Query(..., description="Settlement point to explain"),
    k: int = Query(15, ge=1, le=500, description="Number of top constraints"),
) -> ExposuresResponse:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, window_start = _resolve(cur)
        meta = _meta_row(cur, run_id, window_start)

        # Stable, unsigned headline (spec §6): max_c |SF[sp,c]| over ALL
        # constraints, independent of k.
        cur.execute(
            "SELECT max(abs(sf)) AS m FROM implied_shift_factors "
            "WHERE run_id = %s AND window_start = %s AND settlement_point = %s",
            (run_id, window_start, sp),
        )
        node_max = cur.fetchone()["m"]

        cur.execute(
            "SELECT i.constraint_key, i.sf, g.lat, g.lon, g.max_abs_sf, "
            "g.binding_hours FROM implied_shift_factors i "
            "LEFT JOIN constraint_geo g ON g.run_id = i.run_id "
            "AND g.window_start = i.window_start "
            "AND g.constraint_key = i.constraint_key "
            "WHERE i.run_id = %s AND i.window_start = %s "
            "AND i.settlement_point = %s "
            "ORDER BY abs(i.sf) DESC LIMIT %s",
            (run_id, window_start, sp, k),
        )
        exposures = [SpExposure(**r) for r in cur.fetchall()]

    return ExposuresResponse(
        sp=sp,
        run_id=run_id,
        window_start=meta["window_start"],
        window_end=meta["window_end"],
        k=k,
        oos_r2=meta["oos_r2"],
        sf_stability=meta["sf_stability"],
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
    min_frac: float = Query(
        0.05, ge=0.0, le=1.0,
        description="Noise floor: drop nodes whose |SF| is below this fraction "
        "of the constraint's peak |SF|. Without it, top-k pads a weakly-fit "
        "constraint (few real nodes) with noise-floor entries.",
    ),
) -> ConstraintReach:
    with get_pool().connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        run_id, window_start = _resolve(cur)
        meta = _meta_row(cur, run_id, window_start)

        cur.execute(
            "SELECT lat, lon, max_abs_sf, n_rail, peak_offrail, binding_hours "
            "FROM constraint_geo "
            "WHERE run_id = %s AND window_start = %s AND constraint_key = %s",
            (run_id, window_start, constraint),
        )
        geo = cur.fetchone() or {}

        # Magnitude floor relative to the constraint's own peak |SF|. A weakly
        # identified constraint has almost no structure past a few nodes, so
        # top-k alone scrapes the noise floor; drop |SF| < min_frac * peak.
        # Unlocated constraints (no geo row → peak None) fall back to no floor.
        peak = geo.get("max_abs_sf")
        floor = min_frac * peak if peak else 0.0

        cur.execute(
            "SELECT settlement_point, sf FROM implied_shift_factors "
            "WHERE run_id = %s AND window_start = %s AND constraint_key = %s "
            "AND abs(sf) >= %s "
            "ORDER BY abs(sf) DESC LIMIT %s",
            (run_id, window_start, constraint, floor, k),
        )
        coords = _sp_coords()
        sps = []
        for r in cur.fetchall():
            lat, lon = coords.get(r["settlement_point"], (None, None))
            sps.append(ReachSp(settlement_point=r["settlement_point"],
                               sf=r["sf"], lat=lat, lon=lon))

    return ConstraintReach(
        constraint_key=constraint,
        run_id=run_id,
        window_start=meta["window_start"],
        window_end=meta["window_end"],
        k=k,
        oos_r2=meta["oos_r2"],
        sf_stability=meta["sf_stability"],
        lat=geo.get("lat"),
        lon=geo.get("lon"),
        max_abs_sf=geo.get("max_abs_sf"),
        n_rail=geo.get("n_rail"),
        peak_offrail=geo.get("peak_offrail"),
        binding_hours=geo.get("binding_hours"),
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
            "SELECT constraint_key, ctype, binding_hours, max_abs_sf, "
            "core_lat, core_lon, lat, lon "
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
            floors = {r["constraint_key"]: (min_frac * r["max_abs_sf"])
                      if r["max_abs_sf"] else 0.0 for r in rows}
            for r in cur.fetchall():
                bucket = by_key[r["constraint_key"]]
                if len(bucket) >= k or abs(r["sf"]) < floors[r["constraint_key"]]:
                    continue
                lat, lon = coords.get(r["settlement_point"], (None, None))
                bucket.append(ReachSp(settlement_point=r["settlement_point"],
                                      sf=r["sf"], lat=lat, lon=lon))

        constraints = [
            OverviewConstraint(
                constraint_key=r["constraint_key"],
                ctype=r["ctype"],
                binding_hours=r["binding_hours"],
                max_abs_sf=r["max_abs_sf"],
                core_lat=r["core_lat"],
                core_lon=r["core_lon"],
                lat=r["lat"],
                lon=r["lon"],
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
