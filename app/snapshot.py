import pypsa
import pandas as pd
import numpy as np
from operating_conditions import apply_operating_conditions
from fragility import compute_fragility, fragility_diagnostics, fragility_plot
from contingency import compute_contingencies, contingency_diagnostics
from ptdf_lodf import get_ptdf_lodf, print_network_diagnostic

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

print_network_diagnostic(n)

#
# Calculate PTDF on current topology
# Given current dispatch, which buses are most exposed to binding constraints
ptdf, lodf_lines, line_names, bus_names = get_ptdf_lodf(n)

#
# FRAGILITY
#

fragility = compute_fragility(n, ptdf, bus_names)
fragility_diagnostics(fragility)
fragility_plot(n, fragility)

#
#  N-1 CONTINGENCY
#
#  stress value: if Line X trips, stress is the sum of all the resulting
#  fractional overloads across all lines after that N-1 contingency

stress_df = compute_contingencies(n, lodf_lines) # line | stress
contingency_diagnostics(n, stress_df, lodf_lines)
