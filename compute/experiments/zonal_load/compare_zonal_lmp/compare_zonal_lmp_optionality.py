"""
Compare model zonal LMP (bus LMPs aggregated to ERCOT weather zones) vs
historical ercot_zonal_lmp, structurally (Spearman) over reference hours.

Run 1: shed-only, SHED_COST=5000, Permian commented out.
    docker compose run --rm compute python \
       /compute/experiments/zonal_load/compare_zonal_lmp/compare_zonal_lmp_optionality.py
"""
import sys; sys.path.insert(0, '/compute')
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd, psycopg, pypsa
from scipy.stats import spearmanr
from config import (PG_DSN, NETWORK_NC, MARGINAL_COSTS_CSV,
                    BUS_WEATHER_LOAD_ZONES_CSV, GENERATOR_MATCHES_ENRICHED_CSV)
from operating_conditions import apply_operating_conditions
from operating_data_adapter import OperatingDataAdapter

OUT_FILE =  Path('/compute/experiments/zonal_load/compare_zonal_lmp/lmp_compare_scenarios_sample.csv')
REF_DATES = Path('/compute/experiments/zonal_load/compare_zonal_lmp/sample_dates.json')
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
    st, _ = n.model.solve(solver_name="highs", io_api="direct")
    if st != "ok": return None
    n.optimize.assign_solution(); n.optimize.assign_duals(assign_all_duals=True)
    return n.buses_t.marginal_price.iloc[0]

def build(op, mc, backbone):
    n = base_network(mc); apply_operating_conditions(n, **op)
    if backbone: add_backbone(n)
    return n

def shed_by_bus(n):
    gp = n.generators_t.p.iloc[0]
    s = gp[gp.index.str.startswith(SHED_PREFIX)]
    s = s[s > 1e-3]
    s.index = s.index.str.replace(SHED_PREFIX, "", regex=False)
    return s  # bus -> shed MW

def zonal(lmp, n, bus2zone):
    load = n.loads.groupby('bus')['p_set'].sum()
    df = pd.DataFrame({'lmp': lmp, 'zone': lmp.index.map(bus2zone),
                       'w': lmp.index.map(load).fillna(0)})
    return df.groupby('zone').apply(
        lambda g: np.average(g.lmp, weights=g.w) if g.w.sum() else g.lmp.mean())

def solve_scenario(op, mc, backbone, two_pass):
    """Returns (lmp_series, network_used_for_weights) or None."""
    n = build(op, mc, backbone); add_shed(n)
    lmp = solve(n)
    if lmp is None: return None
    if not two_pass:
        return lmp, n
    # pass 2: remove shed MW from loads, resolve shed-free for clean prices
    sbb = shed_by_bus(n)
    n2 = build(op, mc, backbone)
    for b, mw in sbb.items():
        mask = n2.loads['bus'] == b
        tot = n2.loads.loc[mask, 'p_set'].sum()
        if tot > 0:
            n2.loads.loc[mask, 'p_set'] -= mw * (n2.loads.loc[mask, 'p_set'] / tot)
    lmp2 = solve(n2)
    return (lmp2, n2) if lmp2 is not None else None

SCENARIOS = [   # (label, backbone, two_pass)
    ("shed_only",      False, False),
    ("backbone_only",  True,  False),
    ("twopass_only",   False, True),
    ("backbone_2pass", True,  True),
]

def main():
    conn = psycopg.connect(PG_DSN)
    cols = pd.read_sql(f"SELECT * FROM {TABLE} LIMIT 3", conn)
    for c in (TS_COL, ZONE_COL, PRICE_COL):
        if c not in cols.columns:
            print(f"!! fix column name: {c!r}"); return

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
    # per scenario: dict ts -> zonal series
    smodel = {lab: [] for lab,_,_ in SCENARIOS}
    ts_list, regimes = [], {}
    from datetime import timedelta
    MAX_RETRY = 6  # try +1h up to 6 times if data missing / solve fails
    for regime, tss in refs.items():
        for _ts in tss:
            ts0 = datetime.fromisoformat(_ts).astimezone(timezone.utc)
            for attempt in range(MAX_RETRY + 1):
                ts = ts0 + timedelta(hours=attempt)
                try:
                    print(f"##### TIMESTAMP: {ts} #####")
                    op = adapter.build(ts, force_global_load_sf=False)
                    if op['meta']['load_scaling_mode'] != 'zonal':
                        raise ValueError("non-zonal load scaling")
                    tmp = {}
                    for lab, bb, tp in SCENARIOS:
                        r = solve_scenario(op, mc, bb, tp)
                        if r is None:
                            raise ValueError(f"{lab} solve failed")
                        lmp, nw = r
                        tmp[lab] = zonal(lmp, nw, bus2zone)
                except Exception as ex:
                    print(f"[skip] {ts.isoformat()} attempt {attempt}: {ex}")
                    continue
                if attempt:
                    print(f"[retry-ok] {ts0.isoformat()} -> {ts.isoformat()}")
                for lab in tmp: smodel[lab].append(tmp[lab].rename(ts))
                ts_list.append(ts); regimes[ts] = regime
                break
            else:
                print(f"[drop] {ts0.isoformat()} failed after {MAX_RETRY} retries")

    models = {lab: pd.DataFrame(rows) for lab, rows in smodel.items()}

    # ERCOT actuals
    lo, hi = min(ts_list), max(ts_list)
    e = pd.read_sql(f"SELECT {TS_COL} ts,{ZONE_COL} zone,{PRICE_COL} lmp FROM {TABLE} "
                    f"WHERE {TS_COL} BETWEEN %s AND %s", conn, params=(lo, hi))
    e['ts'] = pd.to_datetime(e['ts'], utc=True).dt.floor('h')
    ercot = e.groupby(['ts','zone'])['lmp'].mean().unstack()
    hubs = sorted(set(next(iter(models.values())).columns) & set(ercot.columns))

    # correlation per scenario x hub
    print("Spearman rho (model vs ERCOT) by scenario x hub:")
    print(f"  {'scenario':<16}" + "".join(f"{h:>10}" for h in hubs))
    for lab,_,_ in SCENARIOS:
        m = models[lab]; cells = []
        for h in hubs:
            a = m[h].reindex(ts_list); b = ercot[h].reindex(ts_list)
            ok = a.notna() & b.notna()
            rho = spearmanr(a[ok], b[ok])[0] if ok.sum() >= 4 else float('nan')
            cells.append(f"{rho:>+10.2f}")
        print(f"  {lab:<16}" + "".join(cells))

    # long CSV: scenario, ts, regime, zone, model_lmp, ercot_lmp
    rows = []
    for lab,_,_ in SCENARIOS:
        m = models[lab]
        for ts in ts_list:
            for h in hubs:
                rows.append({'scenario':lab,'ts':ts.strftime('%Y-%m-%d %H'),
                             'regime':regimes[ts],'zone':h,
                             'model_lmp':round(float(m[h].get(ts,float('nan'))),1),
                             'ercot_lmp':round(float(ercot[h].get(ts,float('nan'))),1)})
    out = pd.DataFrame(rows)
    out.to_csv(OUT_FILE, index=False)
    print(f"\nwrote {OUT_FILE.read_text()}  (long: scenario,ts,regime,zone,model_lmp,ercot_lmp)")
    # west focus print
    print("\nWest hub by scenario (model $/MWh):")
    piv = out[out.zone=='west'].pivot_table(index=['ts','regime'],columns='scenario',values='model_lmp')
    piv['ercot'] = out[out.zone=='west'].groupby(['ts','regime'])['ercot_lmp'].first()
    pd.set_option('display.width',200,'display.max_rows',200)
    print(piv.to_string())

if __name__ == '__main__':
    main()
