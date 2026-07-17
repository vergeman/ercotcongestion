"""SPIKE 4 (scratch, plan/0092-0001): the 'core' paradigm.

Represent each constraint by ONE point at its intensity-weighted geometric median
(Weiszfeld) instead of the |SF|-weighted mean centroid. The mean sits between a
bimodal constraint's two lobes (central pile); the median sits ON the denser lobe,
and weighting by |SF|^2 pulls it onto the strongest core -> markers move off-center.

Compare de-piling: centroid vs gmedian(|SF|) vs gmedian(|SF|^2). Carry each
constraint's top intense nodes for the hover 'most intense components'.
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


def geomedian(lat, lon, w, iters=64):
    """Weiszfeld weighted geometric median in a local planar frame (lon scaled by
    cos lat), returned as (lat, lon)."""
    lat = np.asarray(lat, float); lon = np.asarray(lon, float); w = np.asarray(w, float)
    lat0 = lat.mean()
    kx = np.cos(np.radians(lat0))
    X = np.column_stack([lat, lon * kx])
    # init at weighted mean
    m = np.average(X, axis=0, weights=w)
    for _ in range(iters):
        d = np.sqrt(((X - m) ** 2).sum(1))
        d = np.maximum(d, 1e-9)
        ww = w / d
        m_new = (X * ww[:, None]).sum(0) / ww.sum()
        if np.hypot(*(m_new - m)) < 1e-9:
            m = m_new; break
        m = m_new
    return float(m[0]), float(m[1] / kx)


def main():
    sp = load_sp_geography()[["lat", "lon"]].dropna()
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT max(window_start) FROM implied_shift_factors WHERE run_id=%s", (RUN_ID,))
        ws = cur.fetchone()[0]
        cur.execute("SELECT constraint_key, settlement_point, sf FROM implied_shift_factors "
                    "WHERE run_id=%s AND window_start=%s", (RUN_ID, ws))
        df = pd.DataFrame(cur.fetchall(), columns=["key", "sp", "sf"])
        cur.execute("SELECT constraint_key, binding_hours, max_abs_sf FROM constraint_geo "
                    "WHERE run_id=%s AND window_start=%s AND lat IS NOT NULL", (RUN_ID, ws))
        meta = {r[0]: (int(r[1] or 0), float(r[2] or 0)) for r in cur.fetchall()}

    df = df.merge(sp, left_on="sp", right_index=True, how="inner")
    df["a"] = df["sf"].abs()
    center_lat, center_lon = sp["lat"].mean(), sp["lon"].mean()

    out = []
    for key, g in df.groupby("key"):
        if key not in meta or len(g) < 2:
            continue
        w = g["a"].to_numpy()
        la, lo = g["lat"].to_numpy(), g["lon"].to_numpy()
        cen = (float(np.average(la, weights=w)), float(np.average(lo, weights=w)))
        gm1 = geomedian(la, lo, w)
        gm2 = geomedian(la, lo, w ** 2)
        gtop = g.sort_values("a", ascending=False).head(6)
        peak = (float(gtop.iloc[0]["lat"]), float(gtop.iloc[0]["lon"]))
        bh, msf = meta[key]
        out.append({
            "key": key, "binding_hours": bh, "max_abs_sf": msf,
            "centroid": cen, "gmed1": gm1, "gmed2": gm2, "peak": peak,
            "nodes": [{"sp": r.sp, "sf": float(r.sf), "lat": float(r.lat),
                       "lon": float(r.lon)} for r in gtop.itertuples()],
        })

    def dist_center(pts):
        return np.array([haversine_km(p[0], p[1], center_lat, center_lon) for p in pts])

    for name in ["centroid", "gmed1", "gmed2", "peak"]:
        d = dist_center([c[name] for c in out])
        # dispersion: mean nearest-neighbor distance among the representative points
        P = np.array([c[name] for c in out])
        D = haversine_km(P[:, 0][:, None], P[:, 1][:, None], P[:, 0][None, :], P[:, 1][None, :])
        np.fill_diagonal(D, np.inf)
        nn = D.min(1)
        print(f"{name:9s} dist-from-center: median {np.median(d):3.0f} km | "
              f"frac within 100km of center {np.mean(d < 100):.2f} | "
              f"mean nearest-neighbor spacing {nn.mean():.1f} km")

    with open("/tmp/core_payload.json", "w") as fh:
        json.dump({"run_id": RUN_ID, "window_start": str(ws),
                   "center": [center_lat, center_lon], "constraints": out}, fh)
    print(f"\nwrote /tmp/core_payload.json ({len(out)} constraints)")


if __name__ == "__main__":
    main()
