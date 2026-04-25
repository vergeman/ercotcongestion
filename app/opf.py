import pypsa
import pandas as pd
import numpy as np
from operating_conditions import apply_operating_conditions
from fragility import compute_fragility, fragility_diagnostics, fragility_plot
from contingency import compute_contingencies, contingency_diagnostics

n = pypsa.Network("/data/processed/Texas2k_series25_case1_summerpeak.nc")

# Apply marginal costs
mc = pd.read_csv("/data/processed/marginal_costs.csv", index_col=0)
n.generators['marginal_cost'] = n.generators.index.map(mc['marginal_cost']).fillna(0)


operating_data = {
    'p_max_pu_by_carrier': {
        'wind': 0.20,      # ERCOT wind typically 15-30% at peak
        'solar': 0.65,     # still producing but sun dropping
        'battery': 0.25,   # partial SOC, limited duration
        'nuclear': 0.95,
        'hydro': 0.50,
        'coal': 0.90,      # available but not forced on
        'gas': 0.90,
        'oil': 0.80,
        'biomass': 0.80,
        'other': 0.80,
    },
    'loads': None,
    'outages': None,
    'line_derate': .9,
    'tx_derate': 0.95
}


apply_operating_conditions(n, **operating_data)


#
# Solve DC-OPF
#
status, cond = n.optimize(solver_name="highs", assign_all_duals=True)
print(f"Status: {status}, {cond}")

# Sanity checks
gen = n.generators_t.p.iloc[0].sum()
load = n.loads_t.p_set.iloc[0].sum()
lmps = n.buses_t.marginal_price.iloc[0]

print(f"\nGen: {gen:.0f} MW | Load: {load:.0f} MW | Balance: {gen - load:+.1f}")
print(f"LMP: min={lmps.min():.2f}, mean={lmps.mean():.2f}, max={lmps.max():.2f}")
print(f"LMP p5/p50/p95: {lmps.quantile([0.05, 0.5, 0.95]).round(2).values}")

print("\nDispatch by fuel:")
dispatch = n.generators.assign(p=n.generators_t.p.iloc[0]).groupby('carrier')['p'].sum().sort_values(ascending=False)
print(dispatch.round(0))


#
# Calculate PTDF on current topology
# Given current dispatch, which buses are most exposed to binding constraints

n.determine_network_topology()
sub = n.sub_networks.obj.iloc[0]
sub.calculate_PTDF()
ptdf_full = sub.PTDF # (n_branches, n_buses) = (lines + transformers, buses)
sub_buses = sub.buses_o  # ordered bus names for this sub-network


#
# FRAGILITY
#

fragility = compute_fragility(n, ptdf_full, sub_buses)
fragility_diagnostics(fragility)
fragility_plot(n, fragility)

#
#  N-1 CONTINGENCY
#
#  stress value: if Line X trips, stress is the sum of all the resulting
#  fractional overloads across all lines after that N-1 contingency

sub.calculate_BODF()   # PyPSA uses BODF (same as LODF for single-line outages)
lodf_full = sub.BODF  # shape: (n_branches, n_branches)

stress_df = compute_contingencies(n, lodf_full) # line | stress
contingency_diagnostics(n, stress_df, lodf_full)
