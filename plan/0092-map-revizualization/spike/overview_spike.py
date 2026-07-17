"""SPIKE 2 (scratch, plan/0092-0001): the OVERVIEW — all constraints at once.

The real design problem is the initial all-constraints view: 1044 constraints
today render as overlapping |SF|-weighted centroid bubbles — an indistinguishable
purple pile, geographically misleading because bimodal constraints collapse their
centroid to the middle.

Dump, for EVERY located constraint in the window, the dipole primitives (two
poles + sep + minority + severity), so the render can compare:
  A. current: centroid bubbles (the blob)
  B. proposed: oriented dipole segments, weighted by binding severity
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


def main() -> None:
    sp = load_sp_geography()[["lat", "lon"]].dropna()
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT max(window_start) FROM implied_shift_factors "
                        "WHERE run_id=%s", (RUN_ID,))
            ws = cur.fetchone()[0]
            cur.execute(
                "SELECT constraint_key, settlement_point, sf "
                "FROM implied_shift_factors WHERE run_id=%s AND window_start=%s",
                (RUN_ID, ws))
            df = pd.DataFrame(cur.fetchall(),
                              columns=["key", "sp", "sf"])
            cur.execute(
                "SELECT constraint_key, binding_hours, max_abs_sf, spread_km, "
                "lat, lon FROM constraint_geo WHERE run_id=%s AND window_start=%s",
                (RUN_ID, ws))
            meta = pd.DataFrame(cur.fetchall(),
                                columns=["key", "binding_hours", "max_abs_sf",
                                         "spread_km", "cen_lat", "cen_lon"]
                                ).set_index("key")

    df = df.merge(sp, left_on="sp", right_index=True, how="inner")
    df["w"] = df["sf"].abs()
    df["sgn"] = np.sign(df["sf"])

    def pole(sub: pd.DataFrame) -> tuple[float, float, float]:
        w = sub["w"].to_numpy(float)
        m = w.sum()
        if m <= 0:
            return (np.nan, np.nan, 0.0)
        return (float((w * sub["lat"]).sum() / m),
                float((w * sub["lon"]).sum() / m), float(m))

    out = []
    for key, g in df.groupby("key"):
        pos = g[g["sf"] > 0]
        neg = g[g["sf"] < 0]
        plat, plon, pm = pole(pos)
        nlat, nlon, nm = pole(neg)
        if not (np.isfinite(plat) and np.isfinite(nlat)):
            continue
        sep = float(haversine_km(plat, plon, nlat, nlon))
        minority = min(pm, nm) / (pm + nm) if (pm + nm) > 0 else 0.0
        m = meta.loc[key] if key in meta.index else None
        out.append({
            "key": key,
            "pole_pos": [round(plat, 4), round(plon, 4)],
            "pole_neg": [round(nlat, 4), round(nlon, 4)],
            "sep_km": round(sep, 1),
            "minority": round(minority, 3),
            "binding_hours": int(m["binding_hours"]) if m is not None and m["binding_hours"] is not None else 0,
            "max_abs_sf": round(float(m["max_abs_sf"]), 3) if m is not None and m["max_abs_sf"] is not None else 0.0,
            "cen": [round(float(m["cen_lat"]), 4), round(float(m["cen_lon"]), 4)] if m is not None and m["cen_lat"] is not None else None,
        })

    out.sort(key=lambda d: d["binding_hours"], reverse=True)
    payload = {"run_id": RUN_ID, "window_start": str(ws), "n": len(out),
               "constraints": out}
    p = "/tmp/overview_payload.json"
    with open(p, "w") as fh:
        json.dump(payload, fh)
    seps = np.array([d["sep_km"] for d in out])
    print(f"window {ws}: {len(out)} located constraints")
    print(f"sep_km: median {np.median(seps):.0f}, p90 {np.percentile(seps,90):.0f}, "
          f"max {seps.max():.0f}")
    print(f"dipoles with sep>150km (visibly oriented): {(seps>150).sum()} "
          f"({100*(seps>150).mean():.0f}%)")
    print(f"wrote {p}")


if __name__ == "__main__":
    main()
