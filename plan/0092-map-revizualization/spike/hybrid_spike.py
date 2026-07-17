"""SPIKE 5 (scratch, plan/0092-0001): form-follows-type hybrid overview.

Per user: GTC/interface -> cluster/region form (diffuse, covers a large area);
transmission -> MST corridor (co-located, a line makes sense); radial -> a point.

Dump top-N constraints by binding with: type, severity, top-K nodes, MST edges,
and the |SF|^2 geo-median 'core'.
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


def mst_edges(nodes):
    n = len(nodes)
    if n < 2:
        return []
    lat = np.array([nd["lat"] for nd in nodes]); lon = np.array([nd["lon"] for nd in nodes])
    D = haversine_km(lat[:, None], lon[:, None], lat[None, :], lon[None, :])
    intree = [False] * n; intree[0] = True
    best = D[0].copy(); parent = [0] * n; edges = []
    for _ in range(n - 1):
        j, bd = -1, np.inf
        for k in range(n):
            if not intree[k] and best[k] < bd:
                bd, j = best[k], k
        if j < 0:
            break
        intree[j] = True; edges.append([parent[j], j])
        for k in range(n):
            if not intree[k] and D[j, k] < best[k]:
                best[k] = D[j, k]; parent[k] = j
    return edges


def geomedian(lat, lon, w, iters=64):
    lat = np.asarray(lat, float); lon = np.asarray(lon, float); w = np.asarray(w, float)
    kx = np.cos(np.radians(lat.mean()))
    X = np.column_stack([lat, lon * kx])
    m = np.average(X, axis=0, weights=w)
    for _ in range(iters):
        d = np.maximum(np.sqrt(((X - m) ** 2).sum(1)), 1e-9)
        ww = w / d
        m = (X * ww[:, None]).sum(0) / ww.sum()
    return [float(m[0]), float(m[1] / kx)]


def ctype(key, n_rail, peak_offrail):
    if (key.split("|", 1)[1] if "|" in key else "").strip().upper() == "BASE CASE":
        return "gtc"
    if (n_rail or 0) >= 1 and (peak_offrail or 0.0) < 0.25:
        return "radial"
    return "transmission"


def main():
    sp = load_sp_geography()[["lat", "lon"]].dropna()
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT max(window_start) FROM implied_shift_factors WHERE run_id=%s", (RUN_ID,))
        ws = cur.fetchone()[0]
        cur.execute("SELECT constraint_key, binding_hours, max_abs_sf, n_rail, peak_offrail "
                    "FROM constraint_geo WHERE run_id=%s AND window_start=%s AND lat IS NOT NULL "
                    "ORDER BY binding_hours DESC LIMIT 70", (RUN_ID, ws))
        meta = cur.fetchall()

        out = []
        for key, bh, msf, n_rail, peak_offrail in meta:
            cur.execute("SELECT settlement_point, sf FROM implied_shift_factors "
                        "WHERE run_id=%s AND window_start=%s AND constraint_key=%s "
                        "ORDER BY abs(sf) DESC", (RUN_ID, ws, key))
            rows = cur.fetchall()
            if not rows:
                continue
            peak = abs(rows[0][1])
            nodes = []
            for spn, sf in rows:
                if abs(sf) < 0.15 * peak or spn not in sp.index:
                    if abs(sf) < 0.15 * peak:
                        break
                    continue
                nodes.append({"sp": spn, "sf": float(sf),
                              "lat": float(sp.loc[spn, "lat"]), "lon": float(sp.loc[spn, "lon"])})
                if len(nodes) >= 16:
                    break
            if len(nodes) < 2:
                continue
            w = np.array([abs(n["sf"]) for n in nodes])
            out.append({
                "key": key, "binding_hours": int(bh), "max_abs_sf": float(msf),
                "type": ctype(key, n_rail, peak_offrail),
                "nodes": nodes, "edges": mst_edges(nodes),
                "core": geomedian([n["lat"] for n in nodes], [n["lon"] for n in nodes], w ** 2),
            })

    with open("/tmp/hybrid_payload.json", "w") as fh:
        json.dump({"run_id": RUN_ID, "window_start": str(ws), "constraints": out}, fh)
    import collections
    print("types:", dict(collections.Counter(c["type"] for c in out)))
    print(f"wrote /tmp/hybrid_payload.json ({len(out)} constraints)")


if __name__ == "__main__":
    main()
