"""
Compare model zonal LMP (bus LMPs aggregated to ERCOT weather zones) vs
historical ercot_zonal_lmp, structurally (Spearman) over reference hours.

Run 1: shed-only, SHED_COST=5000, Permian commented out.
    docker compose run --rm compute python \
       /compute/experiments/zonal_load/compare_zonal_lmp/compare_zonal_lmp.py
"""
import sys; sys.path.insert(0, '/compute')
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd, psycopg, pypsa
from scipy.stats import spearmanr
from config import (PG_DSN, NETWORK_NC, MARGINAL_COSTS_CSV,
                    BUS_WEATHER_LOAD_ZONES_CSV, GENERATOR_MATCHES_ENRICHED_CSV)
from compute.legacy.operating_conditions import apply_operating_conditions
from compute.legacy.operating_data_adapter import OperatingDataAdapter

REF_DATES = Path('/compute/sample_specs/reference_dates.json')
SHED_COST, SHED_PREFIX = 5000.0, "shed_"
import os
BACKBONE = os.environ.get("BACKBONE", "0") == "1"   # BACKBONE=1 to enable
X_PU_PER_MILE = 0.5 / (765.0 ** 2 / 100.0)
S_NOM_765 = 4000.0
# 3 approved import paths only, true reactance (no ring, no x-mult)
APPROVED = [
    ("5317", "1065", 250.0, "dino_long"), ("1065", "1093", 60.0, "long_drill"),
    ("5279", "3024", 220.0, "bell_bighill"), ("3024", "13304", 177.0, "bighill_sand"),
    ("4174", "13181", 300.0, "howard_sols"),
]

# ---- EDIT after the printed schema: table + column names ----
TABLE      = "ercot_zonal_lmp"
TS_COL     = "interval_ts"     # timestamp col
ZONE_COL   = "load_zone"   # zone/zone-name col
PRICE_COL  = "lmp"                # price col
# map ERCOT zone labels -> your weather-zone slugs (fill once schema seen)
ZONE_MAP   = {}  # e.g. {"LZ_WEST":"far_west", ...}


def base_network(mc):
    n = pypsa.Network(NETWORK_NC)
    n.generators['marginal_cost'] = n.generators.index.map(mc['marginal_cost']).fillna(0)
    return n

def add_backbone(n):
    for b0, b1, miles, label in APPROVED:
        n.add("Line", label, bus0=b0, bus1=b1,
              x=float(X_PU_PER_MILE * miles), r=0.0, b=0.0, s_nom=S_NOM_765)

def add_shed(n):
    n.add("Generator", [f"{SHED_PREFIX}{b}" for b in n.buses.index],
          bus=n.buses.index.values, carrier="load_shed",
          marginal_cost=SHED_COST, p_nom=float(n.loads['p_set'].sum()))

def solve(n):
    n.optimize.create_model()
    s, _ = n.model.solve(solver_name="highs", io_api="direct")
    if s != "ok": return None
    n.optimize.assign_solution(); n.optimize.assign_duals(assign_all_duals=True)
    return n.buses_t.marginal_price.iloc[0]


def main():
    conn = psycopg.connect(PG_DSN)
    # 1. show schema so columns can be fixed
    cols = pd.read_sql(f"SELECT * FROM {TABLE} LIMIT 3", conn)
    print(f"{TABLE} columns: {list(cols.columns)}")
    print(cols.to_string(index=False)); print()
    for c in (TS_COL, ZONE_COL, PRICE_COL):
        if c not in cols.columns:
            print(f"!! fix column name: {c!r} not in table"); return

    mc  = pd.read_csv(MARGINAL_COSTS_CSV, index_col=0)
    bz  = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    gen = pd.read_csv(GENERATOR_MATCHES_ENRICHED_CSV)
    bz['zone'] = bz['ercot_weather_zone'].astype(str).str.lower().str.replace(' ','_')
    WZ_TO_HUB = {'far_west':'west','west':'west','north':'north',
                 'north_central':'north','east':'houston','coast':'houston',
                 'south_central':'south','southern':'south'}
    bus2zone = {b: WZ_TO_HUB.get(z, z)
                for b, z in zip(bz['name'].astype(str), bz['zone'])}
    adapter = OperatingDataAdapter(conn, gen, bz, pypsa.Network(NETWORK_NC))

    refs = json.loads(REF_DATES.read_text())
    model_rows, ts_list, regimes = [], [], {}
    for regime, tss in refs.items():
        for _ts in tss:
            ts = datetime.fromisoformat(_ts).astimezone(timezone.utc)
            op = adapter.build(ts, force_global_load_sf=False)
            if op['meta']['load_scaling_mode'] != 'zonal': continue
            n = base_network(mc); apply_operating_conditions(n, **op)
            if BACKBONE: add_backbone(n)
            add_shed(n)
            lmp = solve(n)
            if lmp is None: continue
            load = n.loads.set_index('bus')['p_set']
            df = pd.DataFrame({'lmp': lmp, 'zone': lmp.index.map(bus2zone),
                               'w': lmp.index.map(load).fillna(0)})
            # load-weighted zonal mean (fallback simple mean if zero load)
            zmean = df.groupby('zone').apply(
                lambda g: np.average(g.lmp, weights=g.w) if g.w.sum() else g.lmp.mean())
            model_rows.append(zmean.rename(ts)); ts_list.append(ts); regimes[ts] = regime

    model = pd.DataFrame(model_rows)  # index=ts, cols=zone
    model.index.name = 'ts'

    # 2. pull ERCOT zonal for same hours, resample to hour, map zones
    lo, hi = min(ts_list), max(ts_list)
    e = pd.read_sql(
        f"SELECT {TS_COL} ts,{ZONE_COL} zone,{PRICE_COL} lmp FROM {TABLE} "
        f"WHERE {TS_COL} BETWEEN %s AND %s", conn, params=(lo, hi))
    e['ts'] = pd.to_datetime(e['ts'], utc=True).dt.floor('h')
    if ZONE_MAP: e['zone'] = e['zone'].map(ZONE_MAP).fillna(e['zone'])
    ercot = e.groupby(['ts','zone'])['lmp'].mean().unstack()

    # 3. align on shared (ts, zone), Spearman per zone
    print("Per-zone structural correlation (model vs ERCOT):")
    for z in sorted(set(model.columns) & set(ercot.columns)):
        a = model[z].reindex(ts_list); b = ercot[z].reindex(ts_list)
        m = a.notna() & b.notna()
        if m.sum() < 4: print(f"  {z:<16} n={m.sum()} (too few)"); continue
        rho, p = spearmanr(a[m], b[m])
        print(f"  {z:<16} n={m.sum():2d}  rho={rho:+.2f}  p={p:.3f}")
    print("\nrho>0 = same movement structure. Levels not expected to match.")

    # per-hour long format: one row per (ts, zone)
    hubs = sorted(set(model.columns) & set(ercot.columns))
    long = []
    for ts in ts_list:
        for z in hubs:
            long.append({
                'ts': ts.strftime('%Y-%m-%d %H'), 'regime': regimes[ts], 'zone': z,
                'model_lmp': round(float(model[z].get(ts, np.nan)), 1),
                'ercot_lmp': round(float(ercot[z].get(ts, np.nan)), 1),
            })
    out = pd.DataFrame(long)
    pd.set_option('display.width', 200, 'display.max_rows', 200)
    print("\nPer-hour LMP (model vs ERCOT, $/MWh):")
    print(out.to_string(index=False))
    out.to_csv('/compute/experiments/zonal_load/compare_zonal_lmp/lmp_compare.csv', index=False)
    print("\nwrote /compute/experiments/zonal_load/compare_zonal_lmp/lmp_compare.csv")


if __name__ == '__main__':
    main()
