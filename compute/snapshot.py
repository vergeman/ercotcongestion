import pypsa
import pandas as pd
import numpy as np
import logging
import time

from congestion import (
    modeled_congestion_at, binding_proximity_at, load_weighted_slack,
    modeled_congestion_diagnostics, binding_proximity_diagnostics,
)
from contingency import compute_contingencies_at, contingency_diagnostics
from ptdf_lodf import get_ptdf_lodf
from operating_conditions import stack_time_varying

from config import HIGHS_THREADS
from constants import SHED_COST, SHED_PREFIX
from datetime import datetime


logger = logging.getLogger(__name__)


def _default_solver_options() -> dict:
    """HiGHS options derived from HIGHS_THREADS. >1 enables PAMI."""
    threads = max(1, int(HIGHS_THREADS))
    if threads > 1:
        return {'parallel': 'on', 'threads': threads}
    return {}


def compute_snapshot_batch(
    n: pypsa.Network,
    ts_list: list[datetime],
    op_by_ts: dict[datetime, dict],
    *,
    top_k_contingencies: int = 10,
    enable_load_shed: bool = True,
    shed_cost: float = SHED_COST,
    enable_diagnostics: bool = False,
    solver_options: dict | None = None,
) -> dict[datetime, dict]:
    """Build the PyPSA model once over ts_list, solve, then return one
    result dict per ts with the same schema as the legacy per-ts entry.

    Caller must call apply_static_mutations(n, ...) once per process
    before the first batch — derate / outage / capacity-lock / reactance
    patch are NOT idempotent and live above this function. Time-varying
    inputs (loads, p_max_pu_per_gen) are stacked from each op_by_ts[ts].
    Load-shed generators are sized to the chunk-wide maximum total load
    so every snapshot in the chunk is feasible.

    On infeasibility, returns {ts: {'status': 'infeasible', ...}} for every
    ts; caller is expected to retry with smaller chunks or a global load
    scale-factor fallback.
    """
    if not ts_list:
        return {}

    # PyPSA's snapshot index must be tz-naive. Keep the caller's tz-aware ts
    # as the dict key for results; use naive equivalents for the model.
    naive_by_orig = {ts: pd.Timestamp(ts).tz_convert('UTC').tz_localize(None)
                     if pd.Timestamp(ts).tzinfo is not None
                     else pd.Timestamp(ts)
                     for ts in ts_list}
    naive_list = [naive_by_orig[ts] for ts in ts_list]
    op_by_naive = {naive_by_orig[ts]: op_by_ts[ts] for ts in ts_list}

    sns_index = pd.DatetimeIndex(naive_list)
    n.set_snapshots(sns_index)

    stack_time_varying(n, naive_list, op_by_naive)

    chunk_max_load = float(n.loads_t.p_set.sum(axis=1).max())
    _ensure_load_shed_gens(n, enable_load_shed, chunk_max_load, shed_cost)

    t0 = time.perf_counter()
    n.optimize.create_model()
    t_build = time.perf_counter() - t0
    t0 = time.perf_counter()
    solve_kwargs = {'solver_name': 'highs', 'io_api': 'direct'}
    # Caller override beats settings default. linopy passes additional kwargs
    # through to the underlying solver. For HiGHS, "solver" selects
    # simplex|ipm|pdlp; "parallel"/"threads" enable PAMI.
    solve_kwargs.update(solver_options or _default_solver_options())
    status, condition = n.model.solve(**solve_kwargs)
    t_solve = time.perf_counter() - t0
    logger.info(
        f"compute_snapshot_batch[{len(ts_list)} ts]: "
        f"build={t_build:.1f}s solve={t_solve:.1f}s"
    )

    if status != 'ok':
        logger.warning(f"OPF {status}: {condition}")
        return {
            ts: {
                'status': 'infeasible',
                'condition': condition,
                'meta': {'solver_status': status},
            }
            for ts in ts_list
        }

    n.optimize.assign_solution()
    n.optimize.assign_duals(assign_all_duals=True)
    assert not n._multi_invest, (
        "post_processing shortcut assumes single-period optimization"
    )
    w = n.snapshot_weightings.objective.loc[sns_index]
    n.buses_t.marginal_price = n.buses_t.marginal_price.divide(w, axis=0)

    ptdf, lodf_lines, bus_names = get_ptdf_lodf(n)

    results = {}
    for ts in ts_list:
        naive_ts = naive_by_orig[ts]
        results[ts] = _build_result_at(
            n, naive_ts, op_by_ts[ts], ptdf, lodf_lines, bus_names,
            top_k_contingencies, enable_load_shed, status,
            enable_diagnostics,
        )
    return results


def _ensure_load_shed_gens(n, enabled: bool, p_nom: float, shed_cost: float) -> None:
    """Add one load-shed generator per bus on first call; resize on subsequent."""
    if not enabled:
        return

    shed_names = pd.Index([f"{SHED_PREFIX}{b}" for b in n.buses.index])
    existing = shed_names.intersection(n.generators.index)
    if len(existing) == len(shed_names):
        n.generators.loc[shed_names, 'p_nom'] = p_nom
        n.generators.loc[shed_names, 'marginal_cost'] = shed_cost
        return

    if len(existing) > 0:
        n.remove("Generator", existing.tolist())

    n.add(
        "Generator",
        shed_names.tolist(),
        bus=n.buses.index.values,
        carrier="load_shed",
        marginal_cost=shed_cost,
        p_nom=p_nom,
        p_nom_extendable=False,
    )


def _slice_or_none(df: pd.DataFrame, ts) -> pd.Series | None:
    if df is None or df.empty:
        return None
    return df.loc[ts]


def _build_result_at(
    n, ts, op, ptdf, lodf_lines, bus_names,
    top_k_contingencies, enable_load_shed, solver_status,
    enable_diagnostics: bool,
) -> dict:
    line_mu_up      = _slice_or_none(n.lines_t.mu_upper, ts)
    line_mu_lo      = _slice_or_none(n.lines_t.mu_lower, ts)
    line_p0         = _slice_or_none(n.lines_t.p0, ts)
    line_s_max_pu   = _slice_or_none(n.lines_t.s_max_pu, ts)
    tx_mu_up        = _slice_or_none(n.transformers_t.mu_upper, ts)
    tx_mu_lo        = _slice_or_none(n.transformers_t.mu_lower, ts)
    tx_p0           = _slice_or_none(n.transformers_t.p0, ts)
    tx_s_max_pu     = _slice_or_none(n.transformers_t.s_max_pu, ts)

    mc = modeled_congestion_at(
        n, line_mu_up, line_mu_lo, tx_mu_up, tx_mu_lo,
        ptdf, bus_names,
    )
    slack_weights = load_weighted_slack(n, ts, bus_names)
    bp = binding_proximity_at(
        n, line_p0, tx_p0, line_s_max_pu, tx_s_max_pu,
        ptdf, bus_names, slack_weights=slack_weights,
    )
    if enable_diagnostics:
        modeled_congestion_diagnostics(mc)
        binding_proximity_diagnostics(bp)

    contingencies = compute_contingencies_at(
        n,
        line_p0 if line_p0 is not None else pd.Series(0.0, index=n.lines.index),
        lodf_lines, top_k_contingencies,
    )
    if enable_diagnostics:
        contingency_diagnostics(
            n, contingencies, lodf_lines,
            line_p0 if line_p0 is not None else pd.Series(0.0, index=n.lines.index),
        )

    gp_ts = n.generators_t.p.loc[ts]
    shed_mw = pd.Series(0.0, index=n.buses.index)
    if enable_load_shed:
        s = gp_ts[gp_ts.index.str.startswith(SHED_PREFIX)].copy()
        s.index = s.index.str.replace(SHED_PREFIX, "", regex=False)
        shed_mw = s.reindex(n.buses.index).fillna(0.0)

    shed_buses = shed_mw.index[shed_mw > 1e-3]
    lmps = n.buses_t.marginal_price.loc[ts].copy()
    lmps.loc[shed_buses] = np.nan
    dispatch = gp_ts[~gp_ts.index.str.startswith(SHED_PREFIX)]
    flows = line_p0 if line_p0 is not None else pd.Series(0.0, index=n.lines.index)

    bus_load_zone     = op.get('bus_load_zone')

    mu_up = line_mu_up.abs() if line_mu_up is not None else pd.Series(0.0, index=n.lines.index)
    mu_lo = line_mu_lo.abs() if line_mu_lo is not None else pd.Series(0.0, index=n.lines.index)
    shadow = (mu_up + mu_lo).reindex(n.lines.index).fillna(0)
    binding_mask = shadow > 0.01
    binding_lines = shadow[binding_mask].sort_values(ascending=False)

    total_load = float(n.loads_t.p_set.loc[ts].sum())
    total_gen = float(dispatch.sum())
    ts_objective = _per_snapshot_objective(n, ts)
    meta = {
        'solver_status': solver_status,
        'total_load_mw': total_load,
        'total_gen_mw': total_gen,
        'balance_mw': total_gen - total_load,
        'objective_cost': ts_objective,
        'n_binding_lines': int(binding_mask.sum()),
        'lmp_min': float(lmps.min()),
        'lmp_mean': float(lmps.mean()),
        'lmp_max': float(lmps.max()),
        'modeled_congestion_total': float(mc.sum()),
        'modeled_congestion_abs_total': float(mc.abs().sum()),
        'modeled_congestion_top10_share': float(
            mc.abs().nlargest(10).sum() / mc.abs().sum()
            if mc.abs().sum() > 0 else 0.0
        ),
        'binding_proximity_max': float(bp.max()) if bp.notna().any() else None,
        'binding_proximity_p95': (
            float(bp.quantile(0.95)) if bp.notna().any() else None
        ),
        'load_shed_total_mw': float(shed_mw.sum()),
        'n_shed_buses': int((shed_mw > 1e-3).sum()),
    }
    if bus_load_zone is not None:
        meta['shed_by_zone'] = (
            shed_mw[shed_mw > 1e-3].groupby(bus_load_zone).sum().to_dict()
        )

    return {
        'status': 'ok',
        'modeled_congestion': mc,
        'binding_proximity': bp,
        'lmps': lmps,
        'dispatch': dispatch,
        'flows': flows,
        'binding_lines': list(binding_lines.index),
        'shadow_prices': binding_lines,
        'top_contingencies': contingencies,
        'shed_mw': shed_mw[shed_mw > 1e-3],
        'shed_buses': list(shed_buses),
        'meta': meta,
    }


def _per_snapshot_objective(n, ts) -> float | None:
    """Per-snapshot cost: Σ (gen_p[ts, g] × marginal_cost[g]). The model's
    objective is the chunk sum; we recompute the single-snapshot slice."""
    gp = n.generators_t.p.loc[ts]
    mc = n.generators['marginal_cost'].reindex(gp.index).fillna(0.0)
    weighting = float(n.snapshot_weightings.objective.loc[ts])
    return float((gp * mc).sum() * weighting)
