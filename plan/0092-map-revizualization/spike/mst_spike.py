"""SPIKE 3 (scratch, plan/0092-0001): top-K MST skeletons instead of averaging.

Idea (user): stop collapsing each constraint to averaged pole/centroid points
(which piles everything in the dense center). Instead draw each constraint's
top-K most-exposed settlement points at their REAL coords, connected by a
minimum spanning tree over geographic distance — a stylized "transmission
corridor" that keeps the constraint at its true location and shape.

Emits:
  mst_detail.json   full top-K + MST for a few named constraints (single view)
  mst_overview.json top-K + MST for the top-N constraints by binding hours
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
import psycopg

from compute.mu.geo import haversine_km, load_sp_geography

RUN_ID = "map-v1"
DSN = (f"host={os.environ['PG_HOST']} dbname={os.environ['PG_DATABASE']} "
       f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")

DETAIL_KEYS = [
    "MCCAMY|BASE CASE",          # bimodal GTC/interface
    "LPLMK_LPLNE_1|SBWDDBM5",    # workhorse, 3122 binding h
    "WESTEX|BASE CASE",          # mostly monopole
    "LENSW_PUTN2_1|SCISPUT8",    # railed (peak |SF| 0.98)
]


def mst_edges(nodes: list[dict]) -> list[tuple[int, int]]:
    """Prim's MST over haversine distance. nodes: [{lat,lon,...}]. Returns
    list of (i, j) index pairs."""
    n = len(nodes)
    if n < 2:
        return []
    lat = np.array([nd["lat"] for nd in nodes])
    lon = np.array([nd["lon"] for nd in nodes])
    D = haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
    in_tree = [False] * n
    in_tree[0] = True
    best = D[0].copy()
    parent = [0] * n
    edges = []
    for _ in range(n - 1):
        j = -1
        bd = np.inf
        for k in range(n):
            if not in_tree[k] and best[k] < bd:
                bd, j = best[k], k
        if j < 0:
            break
        in_tree[j] = True
        edges.append((parent[j], j))
        for k in range(n):
            if not in_tree[k] and D[j, k] < best[k]:
                best[k] = D[j, k]
                parent[k] = j
    return edges


def topk_field(conn, ws, key: str, sp: pd.DataFrame, k: int,
               min_frac: float = 0.10) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT settlement_point, sf FROM implied_shift_factors "
            "WHERE run_id=%s AND window_start=%s AND constraint_key=%s "
            "ORDER BY abs(sf) DESC", (RUN_ID, ws, key))
        rows = cur.fetchall()
    if not rows:
        return []
    peak = abs(rows[0][1])
    out = []
    for spn, sf in rows:
        if abs(sf) < min_frac * peak:
            break
        if spn not in sp.index:
            continue
        out.append({"sp": spn, "sf": float(sf),
                    "lat": float(sp.loc[spn, "lat"]),
                    "lon": float(sp.loc[spn, "lon"])})
        if len(out) >= k:
            break
    return out


def span_km(nodes) -> float:
    if len(nodes) < 2:
        return 0.0
    lat = np.array([n["lat"] for n in nodes]); lon = np.array([n["lon"] for n in nodes])
    D = haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
    return float(D.max())


def main():
    sp = load_sp_geography()[["lat", "lon"]].dropna()
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT max(window_start) FROM implied_shift_factors WHERE run_id=%s", (RUN_ID,))
            ws = cur.fetchone()[0]
            cur.execute("SELECT constraint_key, binding_hours, max_abs_sf, n_rail, "
                        "peak_offrail FROM constraint_geo "
                        "WHERE run_id=%s AND window_start=%s AND lat IS NOT NULL "
                        "ORDER BY binding_hours DESC LIMIT 80", (RUN_ID, ws))
            top_meta = cur.fetchall()

        # detail: rich top-K for the named constraints
        detail = []
        for key in DETAIL_KEYS:
            nodes = topk_field(conn, ws, key, sp, k=14, min_frac=0.08)
            if not nodes:
                continue
            detail.append({"key": key, "nodes": nodes,
                           "edges": mst_edges(nodes), "span_km": span_km(nodes)})

        # overview: leaner top-K for the top-N by binding hours
        def ctype(key, n_rail, peak_offrail):
            if (key.split("|", 1)[1] if "|" in key else "").strip().upper() == "BASE CASE":
                return "gtc"
            if (n_rail or 0) >= 1 and (peak_offrail or 0.0) < 0.25:
                return "radial"
            return "transmission"

        overview = []
        for key, bh, msf, n_rail, peak_offrail in top_meta:
            nodes = topk_field(conn, ws, key, sp, k=6, min_frac=0.15)
            if len(nodes) < 2:
                continue
            overview.append({"key": key, "binding_hours": int(bh),
                             "max_abs_sf": float(msf), "nodes": nodes,
                             "type": ctype(key, n_rail, peak_offrail),
                             "edges": mst_edges(nodes), "span_km": span_km(nodes)})

    for name, obj in [("mst_detail", {"run_id": RUN_ID, "window_start": str(ws), "constraints": detail}),
                      ("mst_overview", {"run_id": RUN_ID, "window_start": str(ws), "constraints": overview})]:
        with open(f"/tmp/{name}.json", "w") as fh:
            json.dump(obj, fh)
    spans = [c["span_km"] for c in overview]
    print(f"window {ws}")
    print(f"detail: {len(detail)} constraints")
    print(f"overview: {len(overview)} constraints, top-6 MST each")
    print(f"  span_km (max pairwise dist among top-6): median {np.median(spans):.0f}, "
          f"p90 {np.percentile(spans,90):.0f}")
    print(f"  vs earlier all-node dipole median 263 km")


if __name__ == "__main__":
    main()
