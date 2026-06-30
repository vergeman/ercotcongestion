"""
Find which Series25 expansion candidates relieve the far_west shed — fast.

Instead of trial-solving all ~39k candidates (thousands of OPFs), this:
  1. Solves the zonal load-shed model once per hour (with duals).
  2. Reads the binding lines and their shadow prices (mu) — the constraints
     actually causing the far_west shed. No hardcoded feeder list.
  3. Uses PTDF to score every candidate by how much a flow-canceling
     transaction across its terminals would relieve those binding lines,
     weighted by mu and the candidate's thermal rating. (Pure linear algebra,
     no OPF.)
  4. Trial-solves only the top-K ranked candidates, greedily, to measure
     real shed reduction and cumulative fixed_cost.

This turns thousands of solves into a few dozen.

    docker compose run --rm compute python \
        /compute/experiments/zonal_load/line_expansion_candidates/far_west_candidates.py \
        --candidates /data/raw/Texas2k_series25_case1_summerpeak/Expansion_Planning_Problem_Data/Candidates.csv \
        --top-k 30 --max-lines 8
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
from ptdf_lodf import get_ptdf_lodf

REF_DATES = Path('/compute/sample_specs/reference_dates.json')
SHED_COST = 1e6
N_BINDING = 50   # cap how many binding lines feed the PTDF score


def base_network(mc):
    n = pypsa.Network(NETWORK_NC)
    n.generators['marginal_cost'] = n.generators.index.map(mc['marginal_cost']).fillna(0)
    return n


def add_shed(n):
    names = [f"shed_{b}" for b in n.buses.index]
    n.add("Generator", names, bus=n.buses.index.values, carrier="load_shed",
          marginal_cost=SHED_COST, p_nom=float(n.loads['p_set'].sum()),
          p_nom_extendable=False)


def solve_shed(n, want_duals=False):
    n.optimize.create_model()
    status, cond = n.model.solve(solver_name="highs", io_api="direct")
    if status != "ok":
        return None, None
    n.optimize.assign_solution()
    if want_duals:
        n.optimize.assign_duals(assign_all_duals=True)
    disp = n.generators_t.p.iloc[0]
    shed = disp[disp.index.str.startswith("shed_")]
    total = float(shed[shed > 1e-3].sum())
    mu = None
    if want_duals:
        mu = (n.lines_t.mu_upper.iloc[0].abs() + n.lines_t.mu_lower.iloc[0].abs())
        mu = mu[mu > 0].sort_values(ascending=False).head(N_BINDING)
    return total, mu


def score_candidates(cand, mu, mc):
    """PTDF flow-cancel score per candidate against the binding lines."""
    npt = base_network(mc)
    ptdf, _lodf, bus_names = get_ptdf_lodf(npt)
    bus_col = {b: j for j, b in enumerate(bus_names)}
    line_pos = {ln: i for i, ln in enumerate(npt.lines.index)}

    rows = [line_pos[ln] for ln in mu.index if ln in line_pos]
    w = mu.loc[[ln for ln in mu.index if ln in line_pos]].to_numpy() # mu

    # R: PTDF restricted to the binding lines
    R = ptdf[rows, :]                                   # (k_binding, n_bus)

    fcol = cand['from_bus_number'].astype(str).map(bus_col).to_numpy()
    tcol = cand['to_bus_number'].astype(str).map(bus_col).to_numpy()
    diff = R[:, fcol] - R[:, tcol]                      # (k_binding, n_cand)
    score = (w[:, None] * np.abs(diff)).sum(0) * cand['s1'].to_numpy()
    return score


def run_one(ts, adapter, mc, cand_all, buses_in_net, top_k, max_lines):
    op = adapter.build(ts, force_global_load_sf=False)
    mode = op['meta']['load_scaling_mode']
    print(f"\n{'='*64}\n{ts.isoformat()}  mode={mode}\n{'='*64}")
    if mode != 'zonal':
        print("  data-missing fallback — skipping")
        return

    # 1-2: baseline shed + binding constraints
    n = base_network(mc); apply_operating_conditions(n, **op); add_shed(n)
    base, mu = solve_shed(n, want_duals=True)
    if base is None:
        print("  baseline shed-model failed to solve"); return
    print(f"  baseline far_west shed: {base:,.0f} MW | binding lines: {0 if mu is None else len(mu)}")
    if base < 1.0 or mu is None or mu.empty:
        print("  nothing to relieve"); return

    # 3: PTDF screen -> top-K candidates
    score = score_candidates(cand_all, mu, mc)
    order = np.argsort(score)[::-1]
    pool = cand_all.iloc[order[:top_k]].reset_index(drop=True)
    print(f"  screened {len(cand_all)} candidates -> testing top {len(pool)}")

    # 4: greedy trial-solve within the pool
    def shed_with(idxs):
        nn = base_network(mc)
        for i in idxs:
            r = pool.loc[i]
            nn.add("Line", f"cand_{i}", bus0=str(int(r['from_bus_number'])),
                   bus1=str(int(r['to_bus_number'])), x=float(r['x']),
                   r=float(r['r']), b=float(r['b']), s_nom=float(r['s1']))
        apply_operating_conditions(nn, **op)
        add_shed(nn)
        return solve_shed(nn)[0]

    chosen, cost, cur = [], 0.0, base
    for _ in range(max_lines):
        best, best_shed = None, cur
        for i in pool.index:
            if i in chosen:
                continue
            s = shed_with(chosen + [i])
            if s is not None and s < best_shed - 1e-3:
                best, best_shed = i, s
        if best is None:
            print("  no further pooled candidate reduces shed"); break
        chosen.append(best); cost += float(pool.loc[best, 'fixed_cost'])
        r = pool.loc[best]
        print(f"  +L {r['from_bus_number']}->{r['to_bus_number']} "
              f"({r['category']}, s1={r['s1']:.0f}) | shed {cur:,.0f}->{best_shed:,.0f} MW "
              f"| cum_cost={cost:,.1f}")
        cur = best_shed
        if cur < 1.0:
            print("  far_west fully served."); break
    print(f"  RESULT: {len(chosen)} lines, shed {base:,.0f}->{cur:,.0f} MW, cost {cost:,.1f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--candidates', required=True)
    ap.add_argument('--top-k', type=int, default=30)
    ap.add_argument('--max-lines', type=int, default=8)
    ap.add_argument('--per-regime', type=int, default=1)
    args = ap.parse_args()

    mc = pd.read_csv(MARGINAL_COSTS_CSV, index_col=0)
    bz = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    gen = pd.read_csv(GENERATOR_MATCHES_ENRICHED_CSV)
    conn = psycopg.connect(PG_DSN)
    adapter = OperatingDataAdapter(conn, gen, bz, pypsa.Network(NETWORK_NC))

    buses_in_net = set(base_network(mc).buses.index.astype(str))
    c = pd.read_csv(args.candidates)
    fb = c['from_bus_number'].astype(str); tb = c['to_bus_number'].astype(str)
    cand_all = c[fb.isin(buses_in_net) & tb.isin(buses_in_net)].reset_index(drop=True)
    print(f"candidates with both ends in network: {len(cand_all)}")

    refs = json.loads(REF_DATES.read_text())
    for regime, tss in refs.items():
        print(f"\n########## {regime} ##########")
        for _ts in tss[:args.per_regime]:
            ts = datetime.fromisoformat(_ts).astimezone(timezone.utc)
            run_one(ts, adapter, mc, cand_all, buses_in_net, args.top_k, args.max_lines)


if __name__ == '__main__':
    main()
