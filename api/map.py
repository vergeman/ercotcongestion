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
from datetime import date as date_t

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from psycopg.rows import dict_row

from config import MAP_RUN_ID
from db import get_pool
from models import (
    ConstraintLobe,
    ConstraintReach,
    ExposuresResponse,
    MapMeta,
    MapOverview,
    OverviewConstraint,
    RankedConstraint,
    RankedConstraints,
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
            "SELECT i.constraint_key, i.sf, g.max_abs_sf, "
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
            "SELECT max_abs_sf, n_rail, peak_offrail, binding_hours "
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


def _lobe(nodes: list[tuple[float, float, float]]) -> ConstraintLobe:
    """A signed dipole end from ``(sf, lat, lon)`` triples (one lobe's located
    nodes) — now just their count, which is all the panel's dipole gauge needs.
    Empty → an unlocated/one-sided lobe."""
    return ConstraintLobe(n_nodes=len(nodes))


def _realized_mu_mass(cur, lo, hi) -> dict[str, float]:
    """Σ |shadow_price| over the delivery day per ``constraint_name|contingency_name``
    — the realized-basis μ series, keyed the same way the SF panel is (compute.sf
    .panels), so it aligns to the artifact's constraint index with no name match."""
    cur.execute(
        "SELECT trim(constraint_name) || '|' || trim(contingency_name) AS key, "
        "sum(abs(shadow_price)) AS mass FROM ercot_dam_shadow_prices "
        "WHERE interval_ts >= %s AND interval_ts <= %s AND shadow_price IS NOT NULL "
        "GROUP BY key",
        (lo, hi),
    )
    return {r["key"]: float(r["mass"]) for r in cur.fetchall() if r["mass"] is not None}


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
    # The day's SF + E_mu artifact decoder — lazy so the map module stays light.
    from compute.sf.project import load_sf_mu

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

        cur.execute(
            "SELECT sf_npz FROM forecast_sf_artifact WHERE run_id = %s AND delivery_date = %s",
            (run_id, day),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(
                status_code=503,
                detail=f"no SF+μ artifact for run_id={run_id} on {day}.",
            )
        assert run_id is not None and day is not None  # resolved-or-503 above
        art = load_sf_mu(bytes(row["sf_npz"]))

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
                source_lobe=_lobe(src),
                sink_lobe=_lobe(snk),
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
