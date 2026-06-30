"""
Model-side system-λ estimators for congestion reference prices.

Three estimators are exposed; the active two are:

  lambda_kkt_clean_median(n, ts)
      KKT/PTDF decomposition (spike 0013, Option 4). Reads pre-solved LMPs +
      line/tx/gen duals from n, reconstructs λ̂_i = LMP_i − Σ PTDF[b,i]·shadow_b
      per bus, returns the median over the "clean" set (buses with ≥1
      dispatching unbound real generator, where λ̂_i = c_g exactly).
      Robust estimator, not an identity — see compute/experiments/system_lambda/README.md.

  lambda_merit_order(n, ts)                      [ACTIVE — populates system_lambda_copper_plate]
      Copper-plate λ via merit-order economic dispatch. Mathematically
      equivalent to `lambda_copper_plate` (the Pass-2 LP collapses to
      economic dispatch once line capacities are infinite), but skips the
      LP solve entirely: sort the free real gens by marginal cost, ramp
      cheapest-first until residual load is met, return the straddling
      gen's cost. ~3 s per snapshot → milliseconds.

  lambda_copper_plate(n, ts)                     [DISABLED — kept for sanity-check / fallback]
      The Pass-2 LP-based extraction (spike 0013, Option 5). Same answer
      as merit-order under copper-plate conditions; left in place for
      future cross-validation when needed.

All functions are safe to call after `compute_snapshot_batch` has solved a
chunk — the network still carries Pass 1 primals and duals at that point.
Return None on extraction failure (caller treats as NaN downstream).
"""
import sys

sys.path.insert(0, '/compute/experiments/system_lambda')

import pandas as pd
import pypsa

from ptdf_lodf import get_ptdf_lodf
from operating_conditions import apply_static_mutations
from snapshot import SHED_PREFIX
from kkt import reconstruct_lambda

SOLVER = 'highs'
COPPER_PLATE_FACTOR = 1e6   # multiplier on s_nom; effectively ∞ vs any flow
DUAL_TOL = 1e-6             # gen-mu threshold for at-bound classification
P_TOL = 1e-3                # MW threshold for "dispatching" classification


def _slice_dual(df: pd.DataFrame, ts, w: pd.Series) -> pd.Series | None:
    """Slice a mu DataFrame at ts and divide by snapshot weighting."""
    if df is None or df.empty:
        return None
    return df.divide(w, axis=0).loc[ts]


def _is_shed(name: str) -> bool:
    return name.startswith(SHED_PREFIX)


def lambda_kkt_clean_median(n: pypsa.Network, ts) -> float | None:
    """KKT clean-bus median λ̂ extracted from a solved snapshot.

    Reads LMPs (already divided by weighting in compute_snapshot_batch) and
    per-snapshot line/tx/gen duals (divided here). Identifies the clean-bus
    set (≥1 dispatching unbound real gen, shed gens excluded) and returns
    the median λ̂_i over that set. Returns None if the set is empty.
    """
    sns = n.snapshots
    w = n.snapshot_weightings.objective.reindex(sns)

    lmps = n.buses_t.marginal_price.loc[ts]
    line_mu_up = _slice_dual(n.lines_t.mu_upper,        ts, w)
    line_mu_lo = _slice_dual(n.lines_t.mu_lower,        ts, w)
    tx_mu_up   = _slice_dual(n.transformers_t.mu_upper, ts, w)
    tx_mu_lo   = _slice_dual(n.transformers_t.mu_lower, ts, w)

    gen_p     = n.generators_t.p.loc[ts]
    gen_mu_up = _slice_dual(n.generators_t.mu_upper, ts, w)
    gen_mu_lo = _slice_dual(n.generators_t.mu_lower, ts, w)
    if gen_mu_up is None or gen_mu_lo is None:
        return None
    gen_bus = n.generators['bus']

    # Exclude shed generators from the clean-bus set — their high marginal
    # cost would contaminate λ̂ at any bus where they're dispatching unbound.
    real_mask = ~gen_p.index.to_series().map(_is_shed)
    gen_p_real     = gen_p[real_mask]
    gen_mu_up_real = gen_mu_up.reindex(gen_p_real.index)
    gen_mu_lo_real = gen_mu_lo.reindex(gen_p_real.index)

    unbound     = (gen_mu_up_real.abs() < DUAL_TOL) & (gen_mu_lo_real.abs() < DUAL_TOL)
    dispatching = gen_p_real > P_TOL
    clean_gens  = gen_p_real.index[unbound & dispatching]
    if len(clean_gens) == 0:
        return None
    clean_buses = sorted(set(gen_bus.loc[clean_gens]))

    ptdf, _, bus_names = get_ptdf_lodf(n)
    line_names = list(n.lines.index)
    tx_names   = list(n.transformers.index) or None

    kkt = reconstruct_lambda(
        lmps=lmps,
        line_mu_upper=line_mu_up, line_mu_lower=line_mu_lo,
        tx_mu_upper=tx_mu_up,     tx_mu_lower=tx_mu_lo,
        ptdf=ptdf, bus_names=bus_names,
        line_names=line_names, tx_names=tx_names,
    )

    lh_all = kkt['lambda_hat_per_bus']
    # LMP == 0 exactly = LP-degenerate radial/dead-end bus. Drop.
    nontrivial = lmps.reindex(lh_all.index).abs() > 1e-9
    lh = lh_all.reindex(nontrivial[nontrivial].index)
    lh_clean = lh.reindex(lh.index.intersection(clean_buses)).dropna()
    if lh_clean.empty:
        return None
    return float(lh_clean.median())


def _effective_pu(
    varying_df: pd.DataFrame | None,
    static_series: pd.Series,
    gens,
    ts,
) -> pd.Series:
    """Per-gen p_{min,max}_pu at ts. PyPSA semantics: time-varying override
    takes precedence over static; static fills gens absent from the override."""
    static = static_series.reindex(gens).astype(float)
    if varying_df is None or varying_df.empty or ts not in varying_df.index:
        return static
    overrides = varying_df.reindex(columns=gens).loc[ts]
    return overrides.fillna(static)


def lambda_merit_order(n: pypsa.Network, ts) -> float | None:
    """Copper-plate λ via merit-order economic dispatch.

    Equivalent to lambda_copper_plate(n, ts): under copper-plate (line caps
    lifted to ∞), the Pass-2 LP reduces to single-balance economic dispatch
    on the free real gens. The straddling gen's marginal cost = λ. No LP
    solve, no model build — just sort + cumsum.

    Returns None if no free real gens exist, if total fixed dispatch already
    exceeds total load, or if free gens cannot cover the residual (the LP
    would have needed shed)."""
    sns = n.snapshots
    w = n.snapshot_weightings.objective.reindex(sns)

    gen_p     = n.generators_t.p.loc[ts]
    gen_mu_up = _slice_dual(n.generators_t.mu_upper, ts, w)
    gen_mu_lo = _slice_dual(n.generators_t.mu_lower, ts, w)
    if gen_mu_up is None or gen_mu_lo is None:
        return None

    real_mask  = ~gen_p.index.to_series().map(_is_shed)
    gen_p_real = gen_p[real_mask]
    mu_up_real = gen_mu_up.reindex(gen_p_real.index).fillna(0.0)
    mu_lo_real = gen_mu_lo.reindex(gen_p_real.index).fillna(0.0)
    at_bound   = (mu_up_real.abs() > DUAL_TOL) | (mu_lo_real.abs() > DUAL_TOL)

    fixed_dispatch = float(gen_p_real[at_bound].sum())
    total_load     = float(n.loads_t.p_set.loc[ts].sum())
    residual       = total_load - fixed_dispatch
    if residual < -1e-3:
        return None

    free_gens = gen_p_real.index[~at_bound]
    if len(free_gens) == 0:
        return None

    p_nom   = n.generators['p_nom'].reindex(free_gens).astype(float)
    pmin_pu = _effective_pu(n.generators_t.p_min_pu, n.generators['p_min_pu'],
                            free_gens, ts)
    pmax_pu = _effective_pu(n.generators_t.p_max_pu, n.generators['p_max_pu'],
                            free_gens, ts)
    pmin = (p_nom * pmin_pu).clip(lower=0.0)
    pmax = (p_nom * pmax_pu).clip(lower=0.0)
    mc   = n.generators['marginal_cost'].reindex(free_gens).astype(float)

    if pmax.sum() < residual - 1e-3:
        # Free gens can't cover residual load — LP would have needed shed.
        return None

    # Each free gen starts at p_min; merit-order distributes the rest by
    # ramping cheapest gens up to p_max in order.
    df = pd.DataFrame({'mc': mc, 'pmin': pmin, 'pmax': pmax}).sort_values('mc')
    remaining = residual - float(df['pmin'].sum())
    if remaining < -1e-3:
        # Free gens' minima already exceed residual load.
        return None
    if remaining <= 1e-6:
        # No ramping needed — the cheapest gen with positive headroom would
        # set the price for the next MW.
        for _, row in df.iterrows():
            if float(row['pmax'] - row['pmin']) > 1e-9:
                return float(row['mc'])
        return None  # all free gens have zero headroom — pathological

    for _, row in df.iterrows():
        h = float(row['pmax'] - row['pmin'])
        if h <= 1e-9:
            continue
        if h >= remaining - 1e-6:
            return float(row['mc'])  # this gen straddles → marginal
        remaining -= h
    return None  # unreachable if the pmax-sum feasibility check passed


def lambda_copper_plate(n: pypsa.Network, ts) -> float | None:
    """Pass-2 copper-plate λ via LP. DISABLED by default — use
    lambda_merit_order, which gives the same answer in milliseconds. Kept for
    future cross-validation: if a result from merit-order looks suspect,
    swap this back in and compare.

    On a single-snapshot copy of n:
      * Real at-bound gens (μ_up or μ_lo > DUAL_TOL) → fixed at Pass 1 dispatch.
      * Shed gens → fixed at 0 (keep load-shed out of the marginal stack).
      * Real marginal gens → left free (price-setters).
      * Line/tx s_nom multiplied by COPPER_PLATE_FACTOR (copper plate).

    Re-solves; with no congestion source, LMPs are uniform. Returns the
    median LMP. If the uniformity spread exceeds $1 (a constraint didn't
    lift cleanly) or the solver fails, returns None.
    """
    sns = n.snapshots
    w = n.snapshot_weightings.objective.reindex(sns)

    gen_p_full = n.generators_t.p.loc[ts]
    gen_mu_up  = _slice_dual(n.generators_t.mu_upper, ts, w)
    gen_mu_lo  = _slice_dual(n.generators_t.mu_lower, ts, w)
    if gen_mu_up is None or gen_mu_lo is None:
        return None

    # PyPSA refuses to copy a network with an attached solver model. The
    # primal/dual results stay on n as DataFrames after assign_*; nulling
    # solver_model only drops the linopy model reference.
    if hasattr(n, 'model') and n.model is not None:
        try:
            n.model.solver_model = None
        except Exception:
            pass

    n2 = n.copy()
    n2.set_snapshots(pd.DatetimeIndex([ts]))

    # Ensure per-snapshot bound DataFrames exist so per-gen overrides land.
    if n2.generators_t.p_min_pu.empty:
        n2.generators_t.p_min_pu = pd.DataFrame(index=n2.snapshots)
    if n2.generators_t.p_max_pu.empty:
        n2.generators_t.p_max_pu = pd.DataFrame(index=n2.snapshots)

    for g in gen_p_full.index:
        if _is_shed(g):
            # Shed gens: fix at 0 in Pass 2 regardless of Pass 1 dispatch.
            n2.generators_t.p_min_pu.loc[ts, g] = 0.0
            n2.generators_t.p_max_pu.loc[ts, g] = 0.0
            continue
        mu_up = float(gen_mu_up.get(g, 0.0) or 0.0)
        mu_lo = float(gen_mu_lo.get(g, 0.0) or 0.0)
        if abs(mu_up) <= DUAL_TOL and abs(mu_lo) <= DUAL_TOL:
            continue  # marginal; leave free
        p_nom = float(n2.generators.at[g, 'p_nom'])
        if p_nom <= 0:
            continue
        pu = max(0.0, min(1.0, float(gen_p_full[g]) / p_nom))
        n2.generators_t.p_min_pu.loc[ts, g] = pu
        n2.generators_t.p_max_pu.loc[ts, g] = pu

    apply_static_mutations(
        n2, line_derate=COPPER_PLATE_FACTOR, tx_derate=COPPER_PLATE_FACTOR,
    )

    n2.optimize.create_model()
    status, _ = n2.model.solve(solver_name=SOLVER, io_api='direct')
    if status != 'ok':
        return None

    n2.optimize.assign_solution()
    n2.optimize.assign_duals(assign_all_duals=True)
    w2 = n2.snapshot_weightings.objective.reindex(n2.snapshots)
    lmps2 = n2.buses_t.marginal_price.divide(w2, axis=0).loc[ts].dropna()
    nontrivial = lmps2[lmps2.abs() > 1e-9]
    if nontrivial.empty:
        return None
    spread = float(nontrivial.max() - nontrivial.min())
    if spread > 1.0:
        # Copper plate didn't bind uniform LMPs — extraction failed.
        return None
    return float(nontrivial.median())
