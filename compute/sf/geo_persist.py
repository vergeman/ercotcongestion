"""Persist per-window constraint geography into ``constraint_geo`` (plan/0090).

Sibling to the runner's ``--persist-sf`` path. For a run already in
``implied_shift_factors``, it reads each window's SF matrix back from the DB,
applies ``geo.constraint_geography`` to locate every constraint at its
|SF|-weighted centroid, and upserts one ``constraint_geo`` row per
``(window, constraint)`` — adding ``max_abs_sf`` (peak exposure, the *stable*
summary, spec §6) and ``binding_hours`` (support in the fit window).

Decoupled from the fit on purpose: it runs against an already-persisted
``run_id`` so the weekly refresh job (plan/0090 pending-backfill-job) can
re-locate constraints without refitting the SF matrix.

Leak-safety is inherited: the SF it reads was fit on each honest trailing
window (runner ``--persist-sf``), never a global fit — the geography is
walk-forward-honest by construction (memory sf-map-as-geographic-crosswalk).

    docker compose run --rm compute \
      python -m compute.sf.geo_persist --run-id map-v1
"""
from __future__ import annotations

import argparse
import logging

import numpy as np
import pandas as pd
import psycopg

from compute.config import PG_DSN
from compute.mu.geo import (
    ZONES,
    constraint_core,
    constraint_geography,
    constraint_type,
    load_sp_geography,
)
from compute.sf.panels import load_shadow_prices
from compute.sf.persist import copy_constraint_geo_rows, delete_constraint_geo

log = logging.getLogger("compute.sf.geo_persist")

# |SF| at or above this is "railed" — pinned at the ridge clamp (SF_ABS_CAP=1.0).
RAIL_CAP = 0.999

# Geometry columns constraint_geography always emits; forced present so an
# all-uncoordinated window (known.empty → columnless frame) still yields NaN
# rows rather than a KeyError.
_GEO_COLS = ("geo_lat", "geo_lon", "geo_spread_km", "geo_kv_mean", "geo_kv_max")


def _load_windows(conn, run_id: str) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT window_start, window_end FROM sf_window_meta "
            "WHERE run_id = %s ORDER BY window_start",
            (run_id,),
        )
        return cur.fetchall()


def _load_sf_window(conn, run_id: str, window_start) -> pd.DataFrame:
    """Reconstruct one window's SF matrix (constraint_key × settlement_point).

    Threshold-sparsified at persist time (|sf| < --sf-threshold dropped), so the
    pivot carries NaN for the negligible entries; constraint_geography masks
    those to zero weight, and the |SF|-weighted centroid is dominated by the
    large entries that survived anyway.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT constraint_key, settlement_point, sf "
            "FROM implied_shift_factors WHERE run_id = %s AND window_start = %s",
            (run_id, window_start),
        )
        rows = cur.fetchall()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["constraint_key", "settlement_point", "sf"])
    return df.pivot(index="constraint_key", columns="settlement_point", values="sf")


def _zone_shares(g_row: pd.Series) -> dict:
    """{zone: |SF|-mass share} from the geo_zone_<z> columns, finite only."""
    out = {}
    for z in ZONES:
        col = f"geo_zone_{z.removeprefix('LZ_').lower()}"
        v = g_row.get(col, np.nan)
        if v is not None and np.isfinite(v):
            out[z.removeprefix("LZ_").lower()] = float(v)
    return out


def _window_geo(SF: pd.DataFrame, sp: pd.DataFrame, Mw: pd.DataFrame) -> pd.DataFrame:
    """Assemble the constraint_geo rows for one window from its SF + fit-window M."""
    g = constraint_geography(SF, sp)
    for c in _GEO_COLS:
        if c not in g.columns:
            g[c] = np.nan

    binding = (Mw > 0).sum() if not Mw.empty else pd.Series(dtype=float)

    geo = pd.DataFrame(index=SF.index)
    geo["lat"] = g["geo_lat"]
    geo["lon"] = g["geo_lon"]
    geo["spread_km"] = g["geo_spread_km"]
    geo["kv_mean"] = g["geo_kv_mean"]
    geo["kv_max"] = g["geo_kv_max"]
    geo["zone_shares"] = [_zone_shares(g.loc[k]) for k in SF.index]

    # Shape scalars for the low-confidence verdict (docs §4). The clamp cap is
    # SF_ABS_CAP=1.0; a node pinned at |SF|>=RAIL_CAP is "railed". n_rail counts
    # them; peak_offrail is the top of the graded body beneath the rail (max |SF|
    # among non-railed nodes). Several co-equal rails, or a rail with no body,
    # are the ill-conditioned-ridge signature — not a measured sensitivity.
    absSF = SF.abs()
    geo["max_abs_sf"] = absSF.max(axis=1).reindex(SF.index)
    geo["n_rail"] = (absSF >= RAIL_CAP).sum(axis=1).reindex(SF.index).astype(int)
    geo["peak_offrail"] = absSF.where(absSF < RAIL_CAP).max(axis=1).reindex(SF.index)

    geo["binding_hours"] = binding.reindex(SF.index).fillna(0).astype(int)

    # Overview primitives (plan/0092-0002): the |SF|²-core the map de-piles to,
    # and the type that picks its mark. Both summarise this same honest window.
    core = constraint_core(SF, sp)
    geo["core_lat"] = core["geo_core_lat"]
    geo["core_lon"] = core["geo_core_lon"]
    geo["ctype"] = constraint_type(geo)  # needs n_rail/peak_offrail, set above
    return geo


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run-id", required=True,
                   help="The persisted SF run to locate (e.g. map-v1).")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    sp = load_sp_geography()
    with psycopg.connect(PG_DSN) as conn:
        windows = _load_windows(conn, args.run_id)
        if not windows:
            log.error("no sf_window_meta rows for run_id=%s — run "
                      "compute.jobs.weekly_map --persist-sf first", args.run_id)
            return 3

        # binding_hours needs the shadow-price panel over each fit window; load
        # the full span once and slice, mirroring eval.py.
        lo = min(w[0] for w in windows)
        hi = max(w[1] for w in windows)
        log.info("loading shadow prices for binding_hours over [%s, %s)", lo, hi)
        M = load_shadow_prices(conn, lo, hi)

        n_del = delete_constraint_geo(conn, args.run_id)
        log.info("cleared %d prior constraint_geo rows for run_id=%s",
                 n_del, args.run_id)

        total = 0
        for window_start, window_end in windows:
            SF = _load_sf_window(conn, args.run_id, window_start)
            if SF.empty:
                log.warning("no SF rows for window %s; skipping", window_start)
                continue
            Mw = M.loc[(M.index >= window_start) & (M.index < window_end)]
            geo = _window_geo(SF, sp, Mw)
            n = copy_constraint_geo_rows(conn, args.run_id, window_start, geo)
            total += n
            log.info("window=[%s,%s): %d constraints, %d located",
                     pd.Timestamp(window_start).date(),
                     pd.Timestamp(window_end).date(), n,
                     int(geo["lat"].notna().sum()))
        conn.commit()

    log.info("persisted %d constraint_geo rows for run_id=%s", total, args.run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
