"""
Bus-angle DC OPF in linopy — bypasses PyPSA's flow+KVL formulation.

Why: PyPSA solves DC OPF as flow+KVL, putting dual mass on Kirchhoff cycle
constraints that PTDF cannot recover. In the bus-angle formulation, flows
are eliminated via theta variables: f_l = (theta_bus0 - theta_bus1) / x_l.
KVL is automatically satisfied (it's implicit in single-valued theta), no
KVL duals.

Output: LMPs (duals on nodal balance) that should make the standard PTDF
decomposition `λ̂_i = LMP_i − Σ_b PTDF[b,i] × (μ_up − μ_lo)` close to
machine precision.
"""
import sys
from pathlib import Path

sys.path.insert(0, '/compute')
sys.path.insert(0, str(Path(__file__).parent))

import numpy as np
import pandas as pd
import xarray as xr
import pypsa
import linopy

from ptdf_lodf import _determine_topology_for_ptdf


def solve_bus_angle(n: pypsa.Network) -> dict:
    """Solve single-snapshot DC OPF in bus-angle formulation.

    Vectorized construction via dense bus-susceptance and gen-incidence
    matrices. ~60 MB peak for Texas2k; toy is trivial.
    """
    sns = n.snapshots
    assert len(sns) == 1, 'bus-angle solver: single snapshot only'
    ts = sns[0]

    _determine_topology_for_ptdf(n)
    sub = n.sub_networks.obj.iloc[0]
    sub.calculate_PTDF()  # populates sub.B, sub.slack_bus
    bus_order = list(sub.buses_o)
    slack = sub.slack_bus

    branches = sub.branches()
    branch_index = pd.RangeIndex(len(branches), name='branch')
    branch_bus0 = branches['bus0'].values
    branch_bus1 = branches['bus1'].values
    branch_x    = branches['x_pu_eff'].values.astype(float)
    branch_snom = branches['s_nom'].values.astype(float)

    if n.generators_t.p_max_pu is not None and not n.generators_t.p_max_pu.empty:
        p_max_pu = n.generators_t.p_max_pu.loc[ts].reindex(n.generators.index).fillna(
            n.generators['p_max_pu']
        )
    else:
        p_max_pu = n.generators['p_max_pu']
    p_max = (p_max_pu * n.generators['p_nom']).astype(float)
    p_min = (n.generators['p_min_pu'] * n.generators['p_nom']).astype(float)

    if (n.loads_t.p_set is not None and not n.loads_t.p_set.empty
            and ts in n.loads_t.p_set.index):
        load_per_load = n.loads_t.p_set.loc[ts].reindex(n.loads.index).fillna(
            n.loads['p_set']
        )
    else:
        load_per_load = n.loads['p_set']
    load_per_bus = (
        load_per_load.groupby(n.loads['bus']).sum()
        .reindex(bus_order).fillna(0.0).astype(float)
    )

    # ---- coord setup ----
    bus_i = pd.Index(bus_order, name='bus_i')
    bus_j = pd.Index(bus_order, name='bus_j')
    gen_idx = pd.Index(n.generators.index, name='name')

    n_buses = len(bus_order)
    n_br = len(branches)
    n_gen = len(n.generators)
    bus_to_pos = {b: i for i, b in enumerate(bus_order)}

    # ---- variables ----
    m = linopy.Model()
    theta = m.add_variables(
        lower=-1e3, upper=1e3,
        coords=[bus_j], name='theta',
    )
    gen = m.add_variables(
        lower=p_min, upper=p_max,
        name='gen_p',
    )

    # ---- slack: theta[slack_bus] == 0 ----
    slack_pos = bus_to_pos[slack]
    e_slack = np.zeros(n_buses)
    e_slack[slack_pos] = 1.0
    e_slack_da = xr.DataArray(e_slack, dims=('bus_j',), coords={'bus_j': bus_j})
    m.add_constraints((e_slack_da * theta).sum(dim='bus_j') == 0.0, name='slack')

    # ---- branch flow limits via incidence K[branch, bus_j] ----
    K = np.zeros((n_br, n_buses))
    for l in range(n_br):
        K[l, bus_to_pos[branch_bus0[l]]] += 1.0
        K[l, bus_to_pos[branch_bus1[l]]] -= 1.0
    K_da = xr.DataArray(K, dims=('branch', 'bus_j'),
                        coords={'branch': branch_index, 'bus_j': bus_j})
    flow_expr = (K_da * theta).sum(dim='bus_j')
    snom_x = xr.DataArray(branch_snom * branch_x, dims=('branch',),
                          coords={'branch': branch_index})
    m.add_constraints(flow_expr <=  snom_x, name='flow_upper')
    m.add_constraints(flow_expr >= -snom_x, name='flow_lower')

    # ---- nodal balance: Σ_g_at_i gen[g] − Σ_j B[i,j] × theta[j] == load_i
    # Build G[bus_i, gen] incidence
    G = np.zeros((n_buses, n_gen))
    for k, (g, b) in enumerate(n.generators['bus'].items()):
        if b in bus_to_pos:
            G[bus_to_pos[b], k] = 1.0
    G_da = xr.DataArray(G, dims=('bus_i', 'name'),
                        coords={'bus_i': bus_i, 'name': gen_idx})
    gen_per_bus = (G_da * gen).sum(dim='name')

    # B from sub: dense (manageable at 2751x2751 = 60 MB)
    B_dense = sub.B.toarray()
    B_da = xr.DataArray(B_dense, dims=('bus_i', 'bus_j'),
                        coords={'bus_i': bus_i, 'bus_j': bus_j})
    B_theta = (B_da * theta).sum(dim='bus_j')

    load_da = xr.DataArray(load_per_bus.values, dims=('bus_i',),
                           coords={'bus_i': bus_i})
    m.add_constraints(gen_per_bus - B_theta == load_da, name='nodal_balance')

    # ---- objective ----
    c = n.generators['marginal_cost'].astype(float)
    m.add_objective((c * gen).sum())

    # ---- solve ----
    status, condition = m.solve(solver_name='highs', io_api='direct')
    if status != 'ok':
        return {'status': status, 'condition': condition}

    # ---- extract duals ----
    # LMPs = duals on nodal_balance, indexed by bus_i
    nb_dual = np.asarray(m.dual['nodal_balance']).ravel()
    lmps = pd.Series(nb_dual, index=bus_order, name='lmp')

    mu_up_raw = np.asarray(m.dual['flow_upper']).ravel()
    mu_lo_raw = np.asarray(m.dual['flow_lower']).ravel()
    # Constraint: (theta_bus0 - theta_bus1) <= s_nom * x, dual = ∂obj/∂rhs in
    # units of $/rad. PTDF decomposition expects shadow per MW of flow
    # capacity. Since theta_diff = x × flow, one MW of flow capacity is
    # worth `x` rad of theta_diff capacity: μ_flow = μ_θ × x.
    mu_up = mu_up_raw * branch_x
    mu_lo = mu_lo_raw * branch_x
    branch_names = list(branches.index.get_level_values('name'))
    n_lines = len(n.lines)

    return {
        'status':     'ok',
        'lmps':       lmps,
        'line_mu_up': pd.Series(mu_up[:n_lines], index=branch_names[:n_lines]),
        'line_mu_lo': pd.Series(mu_lo[:n_lines], index=branch_names[:n_lines]),
        'tx_mu_up':   pd.Series(mu_up[n_lines:], index=branch_names[n_lines:]),
        'tx_mu_lo':   pd.Series(mu_lo[n_lines:], index=branch_names[n_lines:]),
        'objective':  float(m.objective.value),
        'bus_order':  bus_order,
        'branch_order': branch_names,
    }
