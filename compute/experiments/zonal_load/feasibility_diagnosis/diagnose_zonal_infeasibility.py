"""
Localize WHY zonal load scaling drives the OPF infeasible — across every
reference timestamp, so you can see it's the same zone/corridor each time.

Drop in compute/ (sibling of snapshot.py) and run in the compute container:

    docker compose run --rm compute python \
       /compute/experiments/zonal_load/feasibility_diagnosis/diagnose_zonal_infeasibility.py
    docker compose run --rm compute python \
       /compute/experiments/zonal_load/feasibility_diagnosis/diagnose_zonal_infeasibility.py \
       --ts 2025-07-29T20:00:00+00:00

For each timestamp it prints:

  1. SCALING MODE the adapter actually took (zonal vs data-missing global_fallback)
  2. PER-ZONE SCALE TABLE: tamu_mw, ercot_mw, shares, scale, scale/global.
     The zone with scale/global >> 1 is where zonal piles load on top of global.
  3. NON-ERCOT EXPOSURE: scaled load sitting on buses whose generators are
     zeroed (p_max_pu=0) and must import across the boundary.
  4. LOAD-SHED FEASIBILITY MAP for the ZONAL distribution (high-cost shed gen at
     every bus => never infeasible). Nonzero shed = the pocket the real OPF
     could not serve. Reported by weather zone + the saturated feeder lines.
     GLOBAL is solved the same way as a control (should shed ~0).

At the end it aggregates the top shed weather zone across all hours — that
single line is the answer to "why almost every run."

Requires only read access to the DB + .nc; touches nothing in _scale_loads.
"""
import sys
sys.path.insert(0, '/compute')

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import psycopg
import pypsa

from config import (
    PG_DSN, NETWORK_NC,
    MARGINAL_COSTS_CSV, BUS_WEATHER_LOAD_ZONES_CSV, GENERATOR_MATCHES_ENRICHED_CSV,
)
from operating_conditions import apply_operating_conditions
from operating_data_adapter import OperatingDataAdapter

SHED_COST = 1e6  # $/MWh, far above any real marginal cost
REF_DATES = Path('/compute/profiling/reference_dates.json')


# ---------------------------------------------------------------------------

def zone_scale_table(adapter, op):
    st = adapter._static
    tamu = st.static_loads.groupby(st.load_weather_zone).sum()
    ercot = op['loads'].groupby(st.load_weather_zone).sum()
    gscale = op['loads'].sum() / st.static_total
    tbl = pd.DataFrame({'tamu_mw': tamu, 'ercot_mw': ercot})
    tbl['tamu_share'] = tbl['tamu_mw'] / tbl['tamu_mw'].sum()
    tbl['ercot_share'] = tbl['ercot_mw'] / tbl['ercot_mw'].sum()
    tbl['scale'] = tbl['ercot_mw'] / tbl['tamu_mw']
    tbl['scale_vs_global'] = tbl['scale'] / gscale
    return tbl.sort_values('scale_vs_global', ascending=False), gscale


def non_ercot_exposure(adapter, op, n):
    st = adapter._static
    zeroed = n.generators.loc[st.non_ercot_gens, 'bus'].astype(str).unique()
    load_bus = n.loads['bus'].astype(str)
    on_zeroed = load_bus.isin(zeroed).values
    scaled = op['loads'].reindex(n.loads.index).fillna(0.0)
    return float(scaled[on_zeroed].sum()), float(scaled.sum()), int(len(zeroed))


def solve_with_shedding(n, op):
    apply_operating_conditions(n, **op)
    names = [f"shed_{b}" for b in n.buses.index]
    # PyPSA >=1.0 removed madd; n.add broadcasts over a list of names.
    n.add("Generator", names, bus=n.buses.index.values, carrier="load_shed",
          marginal_cost=SHED_COST, p_nom=float(n.loads['p_set'].sum()),
          p_nom_extendable=False)
    n.optimize.create_model()
    status, cond = n.model.solve(solver_name="highs", io_api="direct")
    if status != "ok":
        return status, cond, None, n
    n.optimize.assign_solution()
    n.optimize.assign_duals(assign_all_duals=True)
    disp = n.generators_t.p.iloc[0]
    shed = disp[disp.index.str.startswith("shed_")]
    shed.index = shed.index.str.replace("shed_", "", regex=False)
    return "ok", None, shed[shed > 1e-3], n


def shed_by_zone(shed, adapter, n):
    load_bus = n.loads['bus'].astype(str)
    bus_to_wz = dict(zip(load_bus.values, adapter._static.load_weather_zone.values))
    wz = shed.index.map(bus_to_wz)
    return shed.groupby(wz).sum().sort_values(ascending=False)


def saturated_lines(n, k=8):
    mu = (n.lines_t.mu_upper.iloc[0].abs() + n.lines_t.mu_lower.iloc[0].abs())
    return mu[mu > 0.01].sort_values(ascending=False).head(k)


# ---------------------------------------------------------------------------

def analyze(ts, adapter, mc):
    def fresh():
        n = pypsa.Network(NETWORK_NC)
        n.generators['marginal_cost'] = n.generators.index.map(mc['marginal_cost']).fillna(0)
        return n

    op = adapter.build(ts, force_global_load_sf=False)
    mode = op['meta']['load_scaling_mode']
    print(f"\n{'='*72}\n{ts.isoformat()}   adapter mode = {mode}\n{'='*72}")
    if mode != 'zonal':
        print("  data-missing fallback — not a zonal test; skipping.")
        return None

    tbl, gscale = zone_scale_table(adapter, op)
    print(f"\n  per-zone scale (global_scale={gscale:.3f}):")
    print(tbl.round(3).to_string())

    nz_mw, tot_mw, nz_buses = non_ercot_exposure(adapter, op, fresh())
    print(f"\n  non-ercot exposure: {nz_mw:,.0f} MW on {nz_buses} zeroed-gen buses "
          f"({100*nz_mw/max(tot_mw,1):.1f}% of system)")

    print("\n  load-shed map:")
    top_zone = None
    for label, force in (("GLOBAL", True), ("ZONAL", False)):
        op_x = adapter.build(ts, force_global_load_sf=force)
        st, cond, shed, n = solve_with_shedding(fresh(), op_x)
        if st != "ok":
            print(f"    [{label}] shed-model {st}: {cond}")
            continue
        if shed is None or shed.empty:
            print(f"    [{label}] no shed (feasible)")
            continue
        bz = shed_by_zone(shed, adapter, n)
        print(f"    [{label}] shed {shed.sum():,.0f} MW; by zone: "
              + ", ".join(f"{z}={v:,.0f}" for z, v in bz.items()))
        if label == "ZONAL":
            top_zone = bz.index[0] if len(bz) else None
            sl = saturated_lines(n)
            if not sl.empty:
                print("           saturated feeders: "
                      + ", ".join(f"{ln}={mu:.1f}" for ln, mu in sl.items()))
    return top_zone


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ts', help="single ISO ts; omit to sweep reference_dates.json")
    args = ap.parse_args()

    mc = pd.read_csv(MARGINAL_COSTS_CSV, index_col=0)
    bz = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    gen = pd.read_csv(GENERATOR_MATCHES_ENRICHED_CSV)
    conn = psycopg.connect(PG_DSN)
    adapter = OperatingDataAdapter(conn, gen, bz, pypsa.Network(NETWORK_NC))

    if args.ts:
        timestamps = [datetime.fromisoformat(args.ts)]
    else:
        refs = json.loads(REF_DATES.read_text())
        timestamps = [datetime.fromisoformat(t)
                      for ts_list in refs.values() for t in ts_list]

    tally = defaultdict(float)
    for ts in timestamps:
        ts = ts.astimezone(timezone.utc)
        try:
            tz = analyze(ts, adapter, mc)
            if tz:
                tally[tz] += 1
        except Exception as e:
            print(f"  {ts}: error {type(e).__name__}: {e}")

    if tally:
        print(f"\n{'='*72}\nTOP ZONAL-INFEASIBLE SHED ZONE across hours:")
        for z, c in sorted(tally.items(), key=lambda kv: -kv[1]):
            print(f"  {z:<18} {int(c)} hours")


if __name__ == '__main__':
    main()
