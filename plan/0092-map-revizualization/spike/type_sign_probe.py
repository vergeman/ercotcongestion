"""Probe: sign asymmetry, constraint-type separability, shared-node conflicts.
(scratch, plan/0092-0001)

Q1 Is +SF (import) systematically the stronger side? -> peak-node sign, top-K sign mix
Q2 Do settlement points appear in many constraints with OPPOSITE signs? (shared-node)
Q3 Can we classify GTC / radial / transmission from existing fields, and how many each?
"""
from __future__ import annotations

import os
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
import psycopg

RUN_ID = "map-v1"
DSN = (f"host={os.environ['PG_HOST']} dbname={os.environ['PG_DATABASE']} "
       f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")
RAIL_CAP = 0.999


def classify(key, n_rail, peak_offrail, span_km, minority):
    contingency = key.split("|", 1)[1] if "|" in key else ""
    if contingency.strip().upper() == "BASE CASE":
        return "GTC/interface"
    nr = n_rail or 0
    po = peak_offrail if peak_offrail is not None else 0.0
    if nr >= 1 and po < 0.25:
        return "radial/pocket"
    return "transmission"


def main():
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT max(window_start) FROM implied_shift_factors WHERE run_id=%s", (RUN_ID,))
        ws = cur.fetchone()[0]
        cur.execute("SELECT constraint_key, settlement_point, sf FROM implied_shift_factors "
                    "WHERE run_id=%s AND window_start=%s", (RUN_ID, ws))
        df = pd.DataFrame(cur.fetchall(), columns=["key", "sp", "sf"])
        cur.execute("SELECT constraint_key, n_rail, peak_offrail, spread_km, binding_hours "
                    "FROM constraint_geo WHERE run_id=%s AND window_start=%s AND lat IS NOT NULL",
                    (RUN_ID, ws))
        meta = {r[0]: r[1:] for r in cur.fetchall()}

    df["a"] = df["sf"].abs()

    # ---- Q1: sign of the single peak node per constraint; top-8 sign mix ----
    peak_sign = Counter()
    topk_pos_frac = []
    for key, g in df.groupby("key"):
        if key not in meta:
            continue
        g = g.sort_values("a", ascending=False)
        peak_sign["+ (import)" if g.iloc[0]["sf"] > 0 else "- (export)"] += 1
        t = g.head(8)
        topk_pos_frac.append((t["sf"] > 0).mean())
    print(f"window {ws}\n")
    print("Q1  sign of each constraint's PEAK |SF| node:")
    tot = sum(peak_sign.values())
    for k, v in peak_sign.most_common():
        print(f"      {k:14s} {v:5d}  ({100*v/tot:.0f}%)")
    print(f"    mean +SF fraction among each constraint's top-8: {np.mean(topk_pos_frac):.2f}")

    # ---- Q2: shared nodes — do SPs flip sign across constraints? ----
    sig = df[df["a"] >= 0.15 * df.groupby("key")["a"].transform("max")]
    per_sp = defaultdict(lambda: [0, 0])  # sp -> [n_pos, n_neg]
    for r in sig.itertuples():
        per_sp[r.sp][0 if r.sf > 0 else 1] += 1
    both = sum(1 for v in per_sp.values() if v[0] > 0 and v[1] > 0)
    print(f"\nQ2  settlement points appearing (|SF|>=0.15*peak) in multiple constraints:")
    print(f"      {len(per_sp)} distinct SPs carry significant SF")
    print(f"      {both} of them ({100*both/len(per_sp):.0f}%) appear with BOTH signs "
          f"across different constraints")
    print("      -> a node's sign is per-constraint; there is no single 'node sign'.")

    # ---- Q3: type classification counts ----
    types = Counter()
    type_bh = defaultdict(int)
    for key, (n_rail, peak_offrail, spread_km, bh) in meta.items():
        t = classify(key, n_rail, peak_offrail, spread_km, 0)
        types[t] += 1
        type_bh[t] += bh or 0
    print(f"\nQ3  constraint-type classification ({len(meta)} located):")
    tb = sum(type_bh.values()) or 1
    for t, c in types.most_common():
        print(f"      {t:16s} {c:5d} constraints   {100*type_bh[t]/tb:4.0f}% of binding-hours")


if __name__ == "__main__":
    main()
