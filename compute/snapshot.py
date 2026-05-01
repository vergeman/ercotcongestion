import pypsa
import pandas as pd
import numpy as np
import logging
from copy import deepcopy
from constants import DEFAULT_P_MAX_PU
from operating_conditions import apply_operating_conditions
from fragility import compute_fragility, fragility_diagnostics, fragility_plot
from contingency import compute_contingencies, contingency_diagnostics
from ptdf_lodf import get_ptdf_lodf, print_network_diagnostic

from config import NETWORK_NC
from datetime import datetime
from operating_data_adapter import OperatingDataAdapter


logger = logging.getLogger(__name__)

def compute_snapshot(n, operating_data, top_k_contingencies = 10, copy_network = False) -> dict[str, any]:
    """
    Compute a full grid snapshot: OPF + fragility + N-1 contingencies.
    Returns
    -------
    snapshot : dict with keys:
        'status'           : 'ok' | 'infeasible'
        'fragility'        : pd.Series (bus → fragility value)
        'lmps'             : pd.Series (bus → $/MWh)
        'basis'            : pd.Series (bus → bus_lmp - zonal_lmp) or NaN
        'dispatch'         : pd.Series (generator → MW)
        'flows'            : pd.Series (line → MW)
        'binding_lines'    : list of line names with non-zero shadow price
        'shadow_prices'    : pd.Series (line → $/MWh, non-zero only)
        'top_contingencies': pd.DataFrame
        'meta'             : dict with totals, cost, counts
    """

    # Note: deepcopy of solved PyPSA networks can fail. Default False for now.
    net = deepcopy(n) if copy_network else n

    apply_operating_conditions(n, **operating_data)

    #
    # Solve DC-OPF
    #
    status, condition = net.optimize(solver_name="highs", assign_all_duals=True)

    if status != 'ok':
        logger.warning(f"OPF {status}: {condition}")
        return {
            'status': 'infeasible',
            'condition': condition,
            'meta': {'solver_status': status},
        }

    print_network_diagnostic(n)

    #
    # Calculate PTDF on current topology
    # Given current dispatch, which buses are most exposed to binding constraints

    ptdf, lodf_lines, bus_names = get_ptdf_lodf(net)

    #
    # FRAGILITY
    #

    fragility = compute_fragility(net, ptdf, bus_names)
    fragility_diagnostics(fragility)
    fragility_plot(n, fragility)

    #
    #  N-1 CONTINGENCY
    #
    #  stress value: if Line X trips, stress is the sum of all the resulting
    #  fractional overloads across all lines after that N-1 contingency

    contingencies = compute_contingencies(net, lodf_lines, top_k_contingencies) # line | stress
    contingency_diagnostics(n, contingencies, lodf_lines)


    # OUTPUTS

    # Market outputs
    lmps = net.buses_t.marginal_price.iloc[0]
    dispatch = net.generators_t.p.iloc[0]
    flows = net.lines_t.p0.iloc[0]

    #
    # BASIS
    #
    #   basis = bus_lmp (model)  -  ERCOT zonal_lmp (real, hourly mean)
    #
    # bus_load_zone and zonal_lmp_by_zone are supplied by the
    # OperatingDataAdapter (adapter).
    #
    # Try to keep compute_snapshot DB-free: the ODA is component that talks to
    # Postgres.


    bus_load_zone     = operating_data.get('bus_load_zone')
    zonal_lmp_by_zone = operating_data.get('zonal_lmp_by_zone') or {}
    basis = _compute_basis(lmps, bus_load_zone, zonal_lmp_by_zone)

    # Binding constraints
    mu_up = net.lines_t.mu_upper.iloc[0].abs()
    mu_lo = net.lines_t.mu_lower.iloc[0].abs()
    shadow = (mu_up + mu_lo).reindex(net.lines.index).fillna(0)
    binding_mask = shadow > 0.01
    binding_lines = shadow[binding_mask].sort_values(ascending=False)

    # Meta
    total_load = net.loads['p_set'].sum()
    total_gen = dispatch.sum()
    meta = {
        'solver_status': status,
        'total_load_mw': float(total_load),
        'total_gen_mw': float(total_gen),
        'balance_mw': float(total_gen - total_load),
        'objective_cost': float(net.objective) if hasattr(net, 'objective') else None,
        'n_binding_lines': int(binding_mask.sum()),
        'lmp_min': float(lmps.min()),
        'lmp_mean': float(lmps.mean()),
        'lmp_max': float(lmps.max()),
        'fragility_total': float(fragility.sum()),
        'fragility_top10_share': float(
            fragility.nlargest(10).sum() / fragility.sum()
            if fragility.sum() > 0 else 0.0
        ),
        'basis_n_resolved': int(basis.notna().sum()),
        'basis_abs_mean': float(basis.abs().mean()) if basis.notna().any() else None
    }

    return {
        'status': 'ok',
        'fragility': fragility,
        'lmps': lmps,
        'basis': basis,
        'dispatch': dispatch,
        'flows': flows,
        'binding_lines': list(binding_lines.index),
        'shadow_prices': binding_lines,
        'top_contingencies': contingencies,
        'meta': meta,
    }

def _compute_basis(
    lmps: pd.Series,
    bus_load_zone: pd.Series | None,
    zonal_lmp_by_zone: dict[str, float | None],
) -> pd.Series:
    """basis[bus] = lmp[bus] - zonal_lmp[zone(bus)].

    NaN where the bus has no ERCOT zone (non_ercot) or where the zone has no
    zonal LMP at this timestamp. Caller writes NaN as NULL to the DB.
    """
    if bus_load_zone is None:
        # No mapping supplied — return all-NaN series aligned to lmps.
        return pd.Series(np.nan, index=lmps.index, name='basis')

    zone_for_bus = bus_load_zone.reindex(lmps.index)

    # Non-ERCOT buses: zonal LMP is undefined.
    zone_lmp_series = zone_for_bus.map(
        {z: v for z, v in zonal_lmp_by_zone.items() if v is not None}
    )
    basis = lmps - zone_lmp_series
    basis.name = 'basis'
    return basis


def run_snapshot_for_ts(
    ts: datetime,
    adapter: OperatingDataAdapter,
    mc: pd.DataFrame,
    network_path: str = NETWORK_NC,
) -> tuple[dict, dict, pypsa.Network]:
    """Build operating data, load network, run OPF for one timestamp.

    Returns (result, op, network). Raises on failure.
    """

    # Build operating data
    op = adapter.build(ts)

    n = pypsa.Network(network_path)

    n.generators['marginal_cost'] = (
        n.generators.index.map(mc['marginal_cost']).fillna(0)
    )

    # Run OPF
    result = compute_snapshot(n, op)

    return result, op, n



if __name__ == '__main__':
    """
    Run compute_snapshot on the bare TAMU network with synthetic carrier-level
    availability.

    No ERCOT data, no timestamp, no DB required.

    Useful for testing OPF / fragility / contingency math in isolation.

    For the real pipeline, see test_snapshot.py and write_snapshots.py.
    """
    n = pypsa.Network("/data/processed/Texas2k_series25_case1_summerpeak.nc")

    # Apply marginal costs
    mc = pd.read_csv("/data/processed/marginal_costs.csv", index_col=0)
    n.generators['marginal_cost'] = n.generators.index.map(mc['marginal_cost']).fillna(0)


    operating_data = {
        'p_max_pu_by_carrier': {
            **DEFAULT_P_MAX_PU,
            'wind': 0.20,      # ERCOT wind typically 15-30% at peak
            'solar': 0.65,     # still producing but sun dropping
        },
        'loads': None,
        'outages': None,
        'line_derate': .9,
        'tx_derate': 0.95
    }

    res = compute_snapshot(n, operating_data)
