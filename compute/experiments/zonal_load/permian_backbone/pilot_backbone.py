"""
Pilot the ERCOT 765-kV Permian backbone on the far_west reference hours.

For each reference hour it:
  1. solves the zonal load-shed model (baseline shed + duals),
  2. adds the three approved 765-kV import paths as equivalent low-x lines
     (endpoints snapped to nearest buses by lat/lon; Permian ends constrained
     to far_west-zone buses),
  3. re-solves and reports shed reduction, whether the backbone carries flow,
     and whether post-add prices are set by real gens (not SHED_COST).
  4. testable permian ring line

    docker compose run --rm compute python \
       /compute/experiments/zonal_load/permian_backbone/pilot_backbone.py

Edit SUBSTATIONS coords once you have exact CCN-filing locations.
"""
import sys
sys.path.insert(0, '/compute')

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
import pypsa

from config import (PG_DSN, NETWORK_NC, MARGINAL_COSTS_CSV,
                    BUS_WEATHER_LOAD_ZONES_CSV, GENERATOR_MATCHES_ENRICHED_CSV)
from operating_conditions import apply_operating_conditions
from operating_data_adapter import OperatingDataAdapter

REF_DATES = Path('/compute/profiling/reference_dates.json')
SHED_COST = 5000
SHED_PREFIX = "shed_"

# --- 765 kV physical params (100 MVA base; ~0.5 ohm/mile, Zbase=765^2/100) ---
X_PU_PER_MILE = 0.5 / (765.0 ** 2 / 100.0)   # ~8.5e-5
S_NOM_765     = 4000.0                         # MW per single circuit; confirm w/ CCN

# Chained station-to-station segments (snapped buses from snap_backbone.py).
# Each segment is its own 765-kV line so flow can enter/exit at intermediate buses.
# (bus0, bus1, miles)
SEGMENTS = [
    # bus0, bus1, miles, label, x_mult
    ("5317", "1065", 250.0, "dino_long",       1.0),
    ("1065", "1093",  60.0, "long_drill",      1.0),
    ("5279", "3024", 220.0, "bell_bighill",    1.0),
    ("3024", "13304",177.0, "bighill_sand",    1.0),
    ("4174", "13181",300.0, "howard_sols",     1.0),
    # Permian interior ring: x_mult>1 so legs share flow instead of one hogging it
    #("1093", "13304", 45.0, "ring_drill_sand", 1),
    #("13304","13181", 35.0, "ring_sand_sols",  1),
    #("13181","1093",  70.0, "ring_sols_drill", 1),
]


def base_network(mc):
    n = pypsa.Network(NETWORK_NC)
    n.generators['marginal_cost'] = n.generators.index.map(mc['marginal_cost']).fillna(0)
    return n


def add_shed(n):
    n.add("Generator", [f"{SHED_PREFIX}{b}" for b in n.buses.index],
          bus=n.buses.index.values, carrier="load_shed",
          marginal_cost=SHED_COST, p_nom=float(n.loads['p_set'].sum()),
          p_nom_extendable=False)


def solve_shed(n, want_duals=False):
    n.optimize.create_model()
    status, cond = n.model.solve(solver_name="highs", io_api="direct")
    if status != "ok":
        return None
    n.optimize.assign_solution()
    n.optimize.assign_duals(assign_all_duals=True)  # needed for marginal_price
    gp = n.generators_t.p.iloc[0]
    shed = gp[gp.index.str.startswith(SHED_PREFIX)]
    out = {'shed_mw': float(shed[shed > 1e-3].sum()), 'status': status}
    # real-gen prices: LMPs at non-shed buses, excluding any bus that shed
    shed_buses = shed[shed > 1e-3].index.str.replace(SHED_PREFIX, "", regex=False)
    lmp = n.buses_t.marginal_price.iloc[0].drop(index=shed_buses, errors='ignore')
    out['lmp_max'] = float(lmp.max())
    out['lmp_mean'] = float(lmp.mean())
    out['n_at_shedcost'] = int((lmp.abs() > SHED_COST * 0.5).sum())  # contaminated?
    if want_duals:
        mu = (n.lines_t.mu_upper.iloc[0].abs() + n.lines_t.mu_lower.iloc[0].abs())
        out['mu'] = mu[mu > 0].sort_values(ascending=False)
    return out


def add_backbone(n):
    added = []
    for b0, b1, miles, label, xm in SEGMENTS:
        x = X_PU_PER_MILE * miles * xm
        n.add("Line", label, bus0=b0, bus1=b1,
              x=float(x), r=0.0, b=0.0, s_nom=S_NOM_765)
        added.append(label)
    return added


def main():
    mc  = pd.read_csv(MARGINAL_COSTS_CSV, index_col=0)
    bz  = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    gen = pd.read_csv(GENERATOR_MATCHES_ENRICHED_CSV)

    # far_west bus mask, aligned to network bus index
    conn = psycopg.connect(PG_DSN)
    adapter = OperatingDataAdapter(conn, gen, bz, pypsa.Network(NETWORK_NC))

    refs = json.loads(REF_DATES.read_text())
    rows = []
    printed_snap = False
    for regime, tss in refs.items():
        for _ts in tss:
            ts = datetime.fromisoformat(_ts).astimezone(timezone.utc)
            op = adapter.build(ts, force_global_load_sf=False)
            if op['meta']['load_scaling_mode'] != 'zonal':
                continue

            # baseline
            n0 = base_network(mc); apply_operating_conditions(n0, **op); add_shed(n0)
            r0 = solve_shed(n0)
            if r0 is None:
                continue

            # with backbone
            n1 = base_network(mc); apply_operating_conditions(n1, **op)
            bb_lines = add_backbone(n1)
            add_shed(n1)
            r1 = solve_shed(n1)
            if not printed_snap:
                print(f"backbone segments: {bb_lines}\n")
                printed_snap = True

            bb_flow = n1.lines_t.p0.iloc[0].reindex(bb_lines).abs().round(0)
            rows.append({
                'ts': ts.isoformat(), 'regime': regime,
                'shed_base': round(r0['shed_mw']),
                'shed_bb':   round(r1['shed_mw']),
                'lmp_max_bb': round(r1['lmp_max'], 1),
                'contam': r1['n_at_shedcost'],
                **{f'f_{lbl}': int(bb_flow[lbl]) for lbl in bb_lines},
            })

    df = pd.DataFrame(rows)
    pd.set_option('display.width', 200, 'display.max_columns', 20)
    print(df.to_string(index=False))
    if not df.empty:
        print(f"\nshed: base {df.shed_base.sum():,} -> bb {df.shed_bb.sum():,} MW "
              f"({df.shed_base.sum() - df.shed_bb.sum():,} relieved)")
        print(f"hours fully served by backbone: {(df.shed_bb < 1).sum()}/{len(df)}")
        print(f"hours with shed-cost-contaminated LMPs after backbone: "
              f"{(df.contam > 0).sum()}/{len(df)}")


if __name__ == '__main__':
    main()
