"""
Sweep the far_west scale cap and measure whether it clears the shed.

For each regime's first reference timestamp, recompute zonal loads with several
zone_scale_cap values (each zone's scale capped at cap * global_scale, residual
redistributed to uncapped zones so the system total is preserved), solve with
load-shed slack, and report far_west shed. shed ~0 => that cap makes it feasible.

    docker compose run --rm compute python /compute/experiments/zonal_load/cap_sweep/cap_sweep.py
    docker compose run --rm compute python \
       /compute/experiments/zonal_load/cap_sweep/cap_sweep.py --caps 1.2 1.3 1.5 2.0
"""

import sys
sys.path.insert(0, '/compute')

import argparse
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
SHED_COST = 1e6


def base_network(mc):
    n = pypsa.Network(NETWORK_NC)
    n.generators['marginal_cost'] = n.generators.index.map(mc['marginal_cost']).fillna(0)
    return n


def capped_loads(adapter, op, cap):
    """Per-bus loads with each zone's scale capped at cap*global_scale."""
    st = adapter._static
    tamu_zone = st.static_loads.groupby(st.load_weather_zone).sum()
    ercot_zone = op['loads'].groupby(st.load_weather_zone).sum()   # raw zonal target
    ercot_total = op['loads'].sum()
    gscale = ercot_total / st.static_total  # global scale factor

    cap_mw = {z: cap * gscale * tamu_zone[z] for z in tamu_zone.index}
    capped = {z: min(ercot_zone[z], cap_mw[z]) for z in tamu_zone.index}
    residual = ercot_total - sum(capped.values())

    # redistribute to uncapped regions - maintain system total equal
    if residual > 1e-6:
        uncapped = [z for z in capped if capped[z] < cap_mw[z] - 1e-9]
        base = sum(capped[z] for z in uncapped)
        for z in uncapped:
            capped[z] += residual * capped[z] / base
    scale_by_zone = {z: capped[z] / tamu_zone[z] for z in capped}
    per_load = st.load_weather_zone.map(scale_by_zone)
    return st.static_loads * per_load


def solve_shed(n, adapter):
    names = [f"shed_{b}" for b in n.buses.index]
    n.add("Generator", names, bus=n.buses.index.values, carrier="load_shed",
          marginal_cost=SHED_COST, p_nom=float(n.loads['p_set'].sum()),
          p_nom_extendable=False)
    n.optimize.create_model()
    status, cond = n.model.solve(solver_name="highs", io_api="direct")
    if status != "ok":
        return None, None
    n.optimize.assign_solution()
    disp = n.generators_t.p.iloc[0]
    shed = disp[disp.index.str.startswith("shed_")]
    shed = shed[shed > 1e-3]
    shed.index = shed.index.str.replace("shed_", "", regex=False)
    load_bus = n.loads['bus'].astype(str)
    b2z = dict(zip(load_bus.values, adapter._static.load_weather_zone.values))
    by_zone = shed.groupby(shed.index.map(b2z)).sum().sort_values(ascending=False)
    return float(shed.sum()), by_zone


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--caps', type=float, nargs='+', default=[1.2, 1.3, 1.5, 2.0])
    ap.add_argument('--per-regime', type=int, default=1)
    args = ap.parse_args()

    mc = pd.read_csv(MARGINAL_COSTS_CSV, index_col=0)
    bz = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    gen = pd.read_csv(GENERATOR_MATCHES_ENRICHED_CSV)
    conn = psycopg.connect(PG_DSN)
    adapter = OperatingDataAdapter(conn, gen, bz, pypsa.Network(NETWORK_NC))

    refs = json.loads(REF_DATES.read_text())
    for regime, tss in refs.items():
        for _ts in tss[:args.per_regime]:
            ts = datetime.fromisoformat(_ts).astimezone(timezone.utc)
            op = adapter.build(ts, force_global_load_sf=False)
            if op['meta']['load_scaling_mode'] != 'zonal':
                continue
            print(f"\n{'='*60}\n{regime}  {ts.isoformat()}\n{'='*60}")
            for cap in args.caps:
                loads = capped_loads(adapter, op, cap)
                op_c = {**op, 'loads': loads}
                n = base_network(mc)
                apply_operating_conditions(n, **op_c)
                total, by_zone = solve_shed(n, adapter)
                if total is None:
                    print(f"  cap={cap:>4}: shed-model FAILED to solve")
                    continue
                fw = by_zone.get('far_west', 0.0)
                tag = "FEASIBLE (no shed)" if total < 1.0 else \
                      f"shed {total:,.0f} MW (far_west {fw:,.0f})"
                print(f"  cap={cap:>4}: {tag}")


if __name__ == '__main__':
    main()
