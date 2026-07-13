"""
Two-pass copper-plate extraction of system λ.

Pass 1: standard DC OPF (reused from kkt_reconstruct._solve_vanilla).
        Yields physically-feasible dispatch and per-generator duals.
Pass 2: on a copy of the network —
          - fix at-bound generators at their Pass 1 levels (p_min_pu = p_max_pu)
          - leave marginal (intermediate-dispatch) generators free
          - lift all line / transformer capacities to ∞ (copper plate)
        Re-solve. With no congestion source, LMPs are uniform across buses
        and equal to the system λ.

Usage:
  docker compose run --rm compute python \\
      /compute/experiments/system_lambda/copper_plate_lambda.py \\
      --mode both --run-id v1
"""
import sys
from pathlib import Path

sys.path.insert(0, '/compute')
sys.path.insert(0, str(Path(__file__).parent))

import argparse
import json
import traceback

import numpy as np
import pandas as pd
import pypsa

from compute.legacy.operating_conditions import apply_static_mutations
from spike_extract import build_toy_network, TOY_SNAPSHOTS, _prepare_texas2k
from kkt_reconstruct import _solve_vanilla

BASE_DIR = Path(__file__).parent
SOLVER = 'highs'
COPPER_PLATE_FACTOR = 1e6   # multiplier on line/tx s_nom; effectively ∞ vs any flow


def _at_bound_gens(pass1: dict, dual_tol: float) -> tuple[set[str], set[str]]:
    """Partition generators into (at_bound, marginal).

    At-bound = either upper or lower bound dual binds in Pass 1.
    Marginal = everything else (free in Pass 2 to set the price)."""
    gen_mu_up = pass1['gen_mu_up']
    gen_mu_lo = pass1['gen_mu_lo']
    all_gens = set(pass1['gen_p'].index)
    if gen_mu_up is None or gen_mu_lo is None:
        return set(), all_gens
    at_upper = set(gen_mu_up.index[gen_mu_up.abs() > dual_tol])
    at_lower = set(gen_mu_lo.index[gen_mu_lo.abs() > dual_tol])
    at_bound = at_upper | at_lower
    marginal = all_gens - at_bound
    return at_bound, marginal


def _build_pass2_network(n_orig: pypsa.Network, pass1: dict, dual_tol: float) -> tuple[pypsa.Network, dict]:
    """Copy n_orig, fix at-bound gens at Pass 1 dispatch, copper-plate the network."""
    # PyPSA refuses to copy a network with an attached solver model. Detach
    # (the Pass 1 primal/dual results stay on n_orig as DataFrames; we don't
    # need the linopy model after extraction).
    if hasattr(n_orig, 'model') and n_orig.model is not None:
        try:
            n_orig.model.solver_model = None
        except Exception:
            pass
    n = n_orig.copy()
    ts = n.snapshots[0]
    gen_p = pass1['gen_p']
    at_bound, marginal = _at_bound_gens(pass1, dual_tol)

    # Ensure the time-varying bound DataFrames exist with the right shape.
    # Per-snapshot overrides in n.generators_t.p_{min,max}_pu take precedence
    # over the static n.generators['p_{min,max}_pu'] columns.
    if n.generators_t.p_min_pu.empty:
        n.generators_t.p_min_pu = pd.DataFrame(index=n.snapshots)
    if n.generators_t.p_max_pu.empty:
        n.generators_t.p_max_pu = pd.DataFrame(index=n.snapshots)

    for g in at_bound:
        p_nom = float(n.generators.at[g, 'p_nom'])
        if p_nom <= 0:
            # Zero-capacity gen cannot influence the dispatch; skip.
            continue
        pu = float(gen_p[g]) / p_nom
        # Clamp tiny numerical excursions outside [0, 1].
        pu = max(0.0, min(1.0, pu))
        n.generators_t.p_min_pu.loc[ts, g] = pu
        n.generators_t.p_max_pu.loc[ts, g] = pu

    # Copper plate: lift line + transformer capacities.
    apply_static_mutations(n, line_derate=COPPER_PLATE_FACTOR, tx_derate=COPPER_PLATE_FACTOR)

    meta = {
        'n_at_bound_gens': len(at_bound),
        'n_marginal_gens': len(marginal),
        'n_generators_total': int(len(n.generators)),
    }
    return n, meta


def _solve_pass2(n: pypsa.Network) -> dict:
    """Solve copper-plate Pass 2. Returns lmps, lambda_hat, uniformity."""
    n.optimize.create_model()
    status, condition = n.model.solve(solver_name=SOLVER, io_api='direct')
    if status != 'ok':
        return {'status': status, 'condition': condition}

    n.optimize.assign_solution()
    n.optimize.assign_duals(assign_all_duals=True)

    sns = n.snapshots
    w = n.snapshot_weightings.objective.reindex(sns)
    ts = sns[0]
    lmps = n.buses_t.marginal_price.divide(w, axis=0).loc[ts]
    lmps_clean = lmps.dropna()

    # Filter LP-degenerate buses (LMP == 0 exactly: dead-end bus with no gen
    # and no load; HiGHS defaults to 0). They contaminate the uniformity check.
    nontrivial = lmps_clean[lmps_clean.abs() > 1e-9]
    if len(nontrivial) == 0:
        return {'status': 'ok', 'lmps': lmps_clean,
                'lambda_hat': float('nan'),
                'uniformity': {'n': 0}, 'error': 'all LMPs degenerate'}

    return {
        'status':     'ok',
        'lmps':       lmps_clean,
        'lambda_hat': float(nontrivial.median()),
        'uniformity': {
            'n':              int(len(nontrivial)),
            'max_minus_min':  float(nontrivial.max() - nontrivial.min()),
            'p95_minus_p5':   float(nontrivial.quantile(0.95) - nontrivial.quantile(0.05)),
            'min':            float(nontrivial.min()),
            'max':            float(nontrivial.max()),
        },
    }


def _verdict(rec: dict) -> str:
    """green: solver ok, LMP max-min < $0.01, ≥1 marginal gen.
       yellow: solver ok, LMP spread $0.01-$1, or only 1 marginal gen.
       red:    solver failure, spread > $1, or zero marginal gens."""
    if 'error' in rec or rec.get('pass2_solver_status') != 'ok':
        return 'red'
    if rec.get('n_marginal_gens', 0) == 0:
        return 'red'
    spread = rec.get('pass2_uniformity', {}).get('max_minus_min', float('inf'))
    if spread > 1.0:
        return 'red'
    if spread > 0.01 or rec.get('n_marginal_gens', 0) < 2:
        return 'yellow'
    return 'green'


# ---------------------------------------------------------------------------
# Mode: toy
# ---------------------------------------------------------------------------

def _run_toy_one(snap, dual_tol: float) -> dict:
    rec: dict = {
        'snapshot_id':     snap.snapshot_id,
        'expected_lambda': snap.expected_lambda,
        'notes':           snap.notes,
    }
    try:
        n = build_toy_network(snap)
        pass1 = _solve_vanilla(n)
        rec['pass1_solver_status'] = pass1['status']
        if pass1['status'] != 'ok':
            rec['error'] = pass1.get('condition')
            return rec
        rec['pass1_lmps'] = {b: float(v) for b, v in pass1['lmps'].items()}
        rec['pass1_dispatch'] = {g: float(v) for g, v in pass1['gen_p'].items()}

        n2, meta = _build_pass2_network(n, pass1, dual_tol)
        rec.update(meta)
        rec['at_bound_gens'] = sorted(_at_bound_gens(pass1, dual_tol)[0])
        rec['marginal_gens'] = sorted(_at_bound_gens(pass1, dual_tol)[1])

        pass2 = _solve_pass2(n2)
        rec['pass2_solver_status'] = pass2['status']
        if pass2['status'] != 'ok':
            rec['error'] = pass2.get('condition')
            return rec
        rec['pass2_lambda_hat'] = pass2['lambda_hat']
        rec['pass2_lmps'] = {b: float(v) for b, v in pass2['lmps'].items()}
        rec['pass2_uniformity'] = pass2['uniformity']
        if snap.expected_lambda is not None:
            rec['lambda_abs_diff'] = abs(pass2['lambda_hat'] - snap.expected_lambda)
    except Exception as e:
        traceback.print_exc()
        rec['error'] = f'{type(e).__name__}: {e}'
    return rec


def run_toy(dual_tol: float) -> dict:
    records = [_run_toy_one(snap, dual_tol) for snap in TOY_SNAPSHOTS]
    return {'mode': 'toy', 'records': records, 'verdict': _verdict_toy(records)}


def _verdict_toy(records: list[dict]) -> str:
    """Toy verdict: all snapshots must produce a uniform Pass 2 (spread < $0.01)
    AND match expected_lambda within $0.01 where known."""
    for r in records:
        if 'error' in r:
            return 'red'
        if r.get('pass2_solver_status') != 'ok':
            return 'red'
        spread = r.get('pass2_uniformity', {}).get('max_minus_min', float('inf'))
        if spread > 0.01:
            return 'red'
        diff = r.get('lambda_abs_diff')
        if diff is not None and diff > 0.01:
            return 'red'
    return 'green'


# ---------------------------------------------------------------------------
# Mode: texas2k
# ---------------------------------------------------------------------------

def _load_kkt_comparators() -> dict:
    """Pull KKT v3 numbers from disk for in-place comparison. Soft-fail if
    the v3 file isn't present (forward-compatible)."""
    path = BASE_DIR / 'kkt_results_v3_texas2k.json'
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        rec = data['records'][0]
        return {
            'kkt_lambda_hat_clean_median':    rec.get('lambda_hat_clean_median'),
            'kkt_lambda_hat_load_weighted':   rec.get('lambda_hat_load_weighted'),
            'kkt_lambda_hat_filtered_median': rec.get('lambda_hat_filtered_median'),
            'kkt_lmp_median':                 rec.get('lmp_median'),
        }
    except Exception:
        return {}


def run_texas2k(dual_tol: float) -> dict:
    n = _prepare_texas2k()
    rec: dict = {
        'snapshot_id':    'texas2k_static',
        'n_buses':        int(len(n.buses)),
        'n_generators':   int(len(n.generators)),
        'n_loads':        int(len(n.loads)),
        'n_lines':        int(len(n.lines)),
        'n_transformers': int(len(n.transformers)),
        'total_load_mw':  float(n.loads['p_set'].sum()),
        'dual_tol':       dual_tol,
    }
    try:
        pass1 = _solve_vanilla(n)
        rec['pass1_solver_status'] = pass1['status']
        if pass1['status'] != 'ok':
            rec['error'] = pass1.get('condition')
            return {'mode': 'texas2k', 'records': [rec], 'verdict': 'red'}

        lmps1 = pass1['lmps'].dropna()
        rec['pass1_lmp_median'] = float(lmps1.median())
        rec['pass1_lmp_summary'] = {
            'min': float(lmps1.min()),
            'p5':  float(lmps1.quantile(0.05)),
            'p50': float(lmps1.median()),
            'p95': float(lmps1.quantile(0.95)),
            'max': float(lmps1.max()),
        }

        n2, meta = _build_pass2_network(n, pass1, dual_tol)
        rec.update(meta)

        pass2 = _solve_pass2(n2)
        rec['pass2_solver_status'] = pass2['status']
        if pass2['status'] != 'ok':
            rec['error'] = pass2.get('condition')
        else:
            rec['pass2_lambda_hat']  = pass2['lambda_hat']
            rec['pass2_uniformity']  = pass2['uniformity']

        rec.update(_load_kkt_comparators())
    except Exception as e:
        traceback.print_exc()
        rec['error'] = f'{type(e).__name__}: {e}'

    return {'mode': 'texas2k', 'records': [rec], 'verdict': _verdict(rec)}


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def _write(payload: dict, path: Path) -> None:
    with open(path, 'w') as f:
        json.dump(payload, f, indent=2, default=str)
    print(f'wrote {path}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=('toy', 'texas2k', 'both'), default='both')
    ap.add_argument('--run-id', default='v1')
    ap.add_argument('--dual-tol', type=float, default=1e-6,
                    help='gen mu threshold for at-bound classification')
    args = ap.parse_args()

    summary: dict[str, str] = {}
    if args.mode in ('toy', 'both'):
        out = run_toy(args.dual_tol)
        _write(out, BASE_DIR / f'cp_results_{args.run_id}_toy.json')
        summary['toy'] = out['verdict']
    if args.mode in ('texas2k', 'both'):
        out = run_texas2k(args.dual_tol)
        _write(out, BASE_DIR / f'cp_results_{args.run_id}_texas2k.json')
        summary['texas2k'] = out['verdict']

    print('\n' + '=' * 50)
    for mode, v in summary.items():
        print(f'  {mode}: {v.upper()}')
    print('=' * 50)


if __name__ == '__main__':
    main()
