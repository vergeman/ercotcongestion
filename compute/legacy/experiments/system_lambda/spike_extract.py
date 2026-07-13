"""
Spike 0013: extract system lambda from PyPSA via a global power balance dual.

Two modes:
  --mode toy       3-bus hand-checkable network, 3 regimes, hand-vs-extracted.
  --mode texas2k   one Texas2k snapshot from baked-in static loads, smoke-only.
  --mode both      run toy then texas2k.

For each solve we run the network twice:
  (A) vanilla — current production path (no GlobalConstraint).
  (B) with a redundant `Σ p_gen == Σ p_load` constraint added; read its dual.

The spike's question: does (B) yield a usable scalar lambda, and does the
primal stay identical to (A)? Result drives Phase 2 reorganization (see
plan/0013-system-lambda.md).

Writes:
  spike_results_<run-id>_toy.json
  spike_results_<run-id>_texas2k.json
"""
import sys
from pathlib import Path

sys.path.insert(0, '/compute')
sys.path.insert(0, str(Path(__file__).parent))

import argparse
import json
import traceback
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd
import pypsa

BASE_DIR = Path(__file__).parent
SOLVER = 'highs'
DUAL_TOL = 1e-3          # $/MWh tolerance for hand-vs-extracted lambda
PRIMAL_TOL = 1e-6        # MW tolerance for dispatch/LMP diff


# ---------------------------------------------------------------------------
# Toy 3-bus network
# ---------------------------------------------------------------------------

@dataclass
class ToySnapshot:
    """One toy regime. expected_lambda is the hand-computed shadow on a
    Σ p_gen == Σ p_load constraint. None means we expect it to fall in a
    range (documented in notes) — verdict will treat it as YELLOW pass.
    s_nom is per-line capacity for this snapshot."""
    snapshot_id: str
    load_b2: float
    load_b3: float
    s_nom: float
    expected_lambda: float | None
    notes: str


TOY_SNAPSHOTS = [
    ToySnapshot(
        snapshot_id='uncongested',
        load_b2=30.0, load_b3=20.0, s_nom=1000.0,
        expected_lambda=20.0,
        notes='Only g_cheap dispatches; system marginal is its $20 MC.',
    ),
    ToySnapshot(
        snapshot_id='congested',
        load_b2=0.0, load_b3=180.0, s_nom=100.0,
        expected_lambda=None,
        notes='Line b1-b3 binds at 100 MW (sending 180 MW b1->b3 splits '
              '2/3 direct = 120 > cap). Solver dispatches some g_peak to '
              'relieve. Lambda lies in [$20, $60]; exact value depends on '
              'which bus the global-balance dual implicitly references.',
    ),
    ToySnapshot(
        snapshot_id='gen_pinned',
        load_b2=200.0, load_b3=250.0, s_nom=1000.0,
        expected_lambda=60.0,
        notes='g_cheap and g_mid pinned at p_max=200 each; g_peak takes '
              'remaining 50 MW at $60.',
    ),
]


def build_toy_network(snap: ToySnapshot) -> pypsa.Network:
    """Triangle: b1-b2, b2-b3, b1-b3. Equal reactance, equal capacity.
    DC OPF (passive_branch_p only). One snapshot at a time so each solve is
    isolated."""
    n = pypsa.Network()
    n.set_snapshots([pd.Timestamp('2025-01-01 00:00')])

    for b in ('b1', 'b2', 'b3'):
        n.add('Bus', b, v_nom=345.0)

    n.add('Generator', 'g_cheap',
          bus='b1', p_nom=200.0, marginal_cost=20.0)
    n.add('Generator', 'g_mid',
          bus='b1', p_nom=200.0, marginal_cost=40.0)
    n.add('Generator', 'g_peak',
          bus='b3', p_nom=200.0, marginal_cost=60.0)

    for name, b0, b1 in (('l_12', 'b1', 'b2'),
                         ('l_23', 'b2', 'b3'),
                         ('l_13', 'b1', 'b3')):
        n.add('Line', name, bus0=b0, bus1=b1,
              x=0.1, r=1e-4, s_nom=snap.s_nom)

    n.add('Load', 'd_b2', bus='b2', p_set=snap.load_b2)
    n.add('Load', 'd_b3', bus='b3', p_set=snap.load_b3)
    return n


# ---------------------------------------------------------------------------
# Solve helpers — vanilla and with-GlobalConstraint
# ---------------------------------------------------------------------------

def _solve(n: pypsa.Network, balance_mode: str) -> dict:
    """Solve n with HiGHS.

    balance_mode:
      'none'     — vanilla, no extra constraint (production parity).
      'native'   — PyPSA n.add('GlobalConstraint', type='primary_energy',
                   sense='==', constant=0). The spike doc's first
                   suggestion.
      'eq'       — manual linopy `Σ Generator-p == Σ p_load` per snapshot,
                   solved with `presolve='off'` (HiGHS presolve flags the
                   redundant equality as infeasible otherwise).
      'ge'       — manual linopy `Σ Generator-p >= Σ p_load` per snapshot.
                   Solves cleanly; we observe whether the dual is non-zero.

    Returns dict with status, lmps, dispatch, objective, extracted_lambda
    (None if balance_mode='none' or extraction failed), and notes.
    """
    extracted_notes: list[str] = []
    if balance_mode == 'native':
        n.add(
            'GlobalConstraint', 'system_balance',
            type='primary_energy', sense='==', constant=0.0,
        )

    n.optimize.create_model()
    m = n.model
    sns = n.snapshots

    if balance_mode in ('eq', 'ge'):
        gen_var = m.variables['Generator-p']
        # linopy names the per-component dim 'name'; summing over 'name'
        # yields per-snapshot total generation.
        gen_total = gen_var.sum(dim='name')
        load_total = n.loads_t.p_set.sum(axis=1).reindex(sns).astype(float)
        load_da = load_total.values
        if balance_mode == 'eq':
            m.add_constraints(gen_total == load_da, name='system_balance')
        else:
            m.add_constraints(gen_total >= load_da, name='system_balance')

    solve_kwargs = {'solver_name': SOLVER, 'io_api': 'direct'}
    if balance_mode == 'eq':
        # HiGHS presolve flags the LP infeasible when this row is exactly
        # redundant with the per-bus nodal balances. Disabling presolve is
        # the cheapest workaround; performance impact at Texas2k scale is
        # observed in the smoke run.
        solve_kwargs['presolve'] = 'off'
    status, condition = n.model.solve(**solve_kwargs)
    if status != 'ok':
        return {
            'status': status, 'condition': condition,
            'lmps': None, 'dispatch': None, 'objective': None,
            'extracted_lambda': None, 'balance_mode': balance_mode,
            'notes': extracted_notes,
        }

    n.optimize.assign_solution()
    n.optimize.assign_duals(assign_all_duals=True)

    w = n.snapshot_weightings.objective.reindex(sns)
    lmps = n.buses_t.marginal_price.divide(w, axis=0)
    dispatch = n.generators_t.p.copy()
    objective = float(n.objective)

    extracted: dict | None = None
    if balance_mode != 'none':
        try:
            if balance_mode == 'native':
                # PyPSA records the dual on n.global_constraints_t.mu when
                # the GlobalConstraint has shadow prices. If absent, PyPSA
                # didn't wire it for this type.
                if hasattr(n.global_constraints_t, 'mu'):
                    mu_df = n.global_constraints_t.mu
                    if 'system_balance' in mu_df.columns:
                        series = mu_df['system_balance'].divide(w)
                        extracted = {str(ts): float(v)
                                     for ts, v in series.items()}
                    else:
                        extracted = {'error': 'mu column missing for '
                                              'system_balance'}
                else:
                    extracted = {'error': 'global_constraints_t has no mu'}
            else:
                dual_da = m.dual['system_balance']
                series = pd.Series(np.asarray(dual_da).ravel(), index=sns)
                series = series.divide(w)
                extracted = {str(ts): float(v) for ts, v in series.items()}
        except Exception as e:
            extracted = {'error': f'{type(e).__name__}: {e}'}

    return {
        'status': 'ok', 'condition': condition,
        'lmps': lmps, 'dispatch': dispatch, 'objective': objective,
        'extracted_lambda': extracted, 'balance_mode': balance_mode,
        'notes': extracted_notes,
    }


def _primal_diff(a: dict, b: dict) -> dict:
    """Compare vanilla and with-balance primal solutions."""
    out: dict = {}
    if a['status'] != 'ok' or b['status'] != 'ok':
        out['error'] = f"status: vanilla={a['status']} with_balance={b['status']}"
        return out

    lmp_diff = (a['lmps'] - b['lmps']).abs()
    disp_diff = (a['dispatch'] - b['dispatch']).abs()
    out['lmp_max_abs_diff']        = float(lmp_diff.max().max())
    out['dispatch_max_abs_diff']   = float(disp_diff.max().max())
    out['objective_abs_diff']      = abs(a['objective'] - b['objective'])
    out['primal_unchanged']        = bool(
        out['lmp_max_abs_diff'] <= PRIMAL_TOL and
        out['dispatch_max_abs_diff'] <= PRIMAL_TOL and
        out['objective_abs_diff'] <= max(1e-6, 1e-6 * abs(a['objective']))
    )
    return out


# ---------------------------------------------------------------------------
# Mode: toy
# ---------------------------------------------------------------------------

BALANCE_MODES = ('native', 'eq', 'ge')


def _mode_summary(res_a: dict, res_b: dict, expected: float | None) -> dict:
    """Per-mode comparison vs vanilla."""
    out: dict = {
        'with_balance_status': res_b['status'],
        'extracted_lambda':    res_b['extracted_lambda'],
        'primal_diff':         _primal_diff(res_a, res_b),
    }
    if (expected is not None
            and isinstance(res_b['extracted_lambda'], dict)
            and 'error' not in res_b['extracted_lambda']):
        vals = list(res_b['extracted_lambda'].values())
        if vals:
            out['lambda_abs_diff'] = abs(vals[0] - expected)
            out['lambda_matches']  = out['lambda_abs_diff'] <= DUAL_TOL
    return out


def run_toy() -> dict:
    records = []
    for snap in TOY_SNAPSHOTS:
        rec: dict = {
            'snapshot_id':     snap.snapshot_id,
            'expected_lambda': snap.expected_lambda,
            'notes':           snap.notes,
        }
        try:
            n_van = build_toy_network(snap)
            res_a = _solve(n_van, balance_mode='none')
            rec['vanilla_status'] = res_a['status']
            if res_a['status'] == 'ok':
                rec['vanilla_lmps'] = {
                    bus: float(v)
                    for bus, v in res_a['lmps'].iloc[0].items()
                }
                rec['vanilla_dispatch'] = {
                    g: float(v)
                    for g, v in res_a['dispatch'].iloc[0].items()
                }

            for mode in BALANCE_MODES:
                n_b = build_toy_network(snap)
                res_b = _solve(n_b, balance_mode=mode)
                rec[f'mode_{mode}'] = _mode_summary(
                    res_a, res_b, snap.expected_lambda,
                )
        except Exception as e:
            traceback.print_exc()
            rec['error'] = f'{type(e).__name__}: {e}'
        records.append(rec)
    return {
        'mode':    'toy',
        'records': records,
        'verdict': _verdict_toy(records),
    }


def _verdict_toy(records: list[dict]) -> str:
    """Per spike doc:
      green  — at least one mode gives primal-unchanged AND lambda matches
               (where expected) across all snapshots.
      yellow — some mode extracts non-zero finite lambda everywhere AND
               primal-unchanged, but lambda doesn't match the hand-computed
               value within tolerance.
      red    — every mode either changes the primal or fails to extract a
               usable lambda.
    """
    for mode in BALANCE_MODES:
        primal_ok = True
        all_extracted_finite = True
        all_match_expected = True
        any_match_known = False
        any_nonzero = False
        for r in records:
            if 'error' in r:
                return 'red'
            ms = r.get(f'mode_{mode}', {})
            primal_ok = primal_ok and ms.get('primal_diff', {}).get(
                'primal_unchanged') is True
            extracted = ms.get('extracted_lambda')
            if not isinstance(extracted, dict) or 'error' in extracted:
                all_extracted_finite = False
                continue
            vals = list(extracted.values())
            if not vals or not all(np.isfinite(v) for v in vals):
                all_extracted_finite = False
            if any(abs(v) > 1e-6 for v in vals):
                any_nonzero = True
            if 'lambda_matches' in ms:
                any_match_known = True
                if not ms['lambda_matches']:
                    all_match_expected = False
        if primal_ok and all_extracted_finite and any_nonzero:
            if any_match_known and all_match_expected:
                return 'green'
            # primal-unchanged + non-zero finite dual but doesn't match hand
            return 'yellow'
    return 'red'


# ---------------------------------------------------------------------------
# Mode: texas2k
# ---------------------------------------------------------------------------

def _prepare_texas2k() -> pypsa.Network:
    """Load Texas2k, apply marginal costs and static mutations, set one
    snapshot using baked-in static loads. No DB / adapter dependency."""
    from config import NETWORK_NC, MARGINAL_COSTS_CSV
    from compute.legacy.operating_conditions import apply_static_mutations

    n = pypsa.Network(NETWORK_NC)
    mc = pd.read_csv(MARGINAL_COSTS_CSV, index_col=0)
    n.generators['marginal_cost'] = (
        n.generators.index.map(mc['marginal_cost']).fillna(0)
    )
    apply_static_mutations(n, line_derate=0.95, tx_derate=0.9)
    ts = pd.Timestamp('2025-01-01 00:00')
    n.set_snapshots([ts])
    n.loads_t.p_set = pd.DataFrame(
        [n.loads['p_set'].values], index=[ts], columns=n.loads.index,
    )
    return n


def run_texas2k() -> dict:
    """Single-snapshot smoke. Runs vanilla and each balance mode that the
    toy network suggested as plausible. Confirms the mechanism (or its
    failure) survives at production scale."""
    n_van = _prepare_texas2k()
    res_a = _solve(n_van, balance_mode='none')

    rec: dict = {
        'snapshot_id':   'texas2k_static',
        'n_buses':       int(len(n_van.buses)),
        'n_generators':  int(len(n_van.generators)),
        'n_loads':       int(len(n_van.loads)),
        'total_load_mw': float(n_van.loads['p_set'].sum()),
        'vanilla_status': res_a['status'],
    }
    if res_a['status'] == 'ok':
        lmps_a = res_a['lmps'].iloc[0].dropna()
        rec['vanilla_lmp_summary'] = {
            'min':  float(lmps_a.min()),
            'p50':  float(lmps_a.median()),
            'mean': float(lmps_a.mean()),
            'max':  float(lmps_a.max()),
        }
        rec['median_lmp_path_a'] = float(lmps_a.median())

    for mode in BALANCE_MODES:
        n_b = _prepare_texas2k()
        try:
            res_b = _solve(n_b, balance_mode=mode)
            rec[f'mode_{mode}'] = _mode_summary(res_a, res_b, expected=None)
        except Exception as e:
            traceback.print_exc()
            rec[f'mode_{mode}'] = {'error': f'{type(e).__name__}: {e}'}

    return {
        'mode':    'texas2k',
        'records': [rec],
        'verdict': _verdict_texas2k(rec),
    }


def _verdict_texas2k(rec: dict) -> str:
    """At Texas2k scale: green if any mode is primal-unchanged AND extracts a
    finite non-zero scalar. Otherwise red."""
    for mode in BALANCE_MODES:
        ms = rec.get(f'mode_{mode}', {})
        if 'error' in ms:
            continue
        if not ms.get('primal_diff', {}).get('primal_unchanged'):
            continue
        extracted = ms.get('extracted_lambda')
        if not isinstance(extracted, dict) or 'error' in extracted:
            continue
        vals = list(extracted.values())
        if vals and all(np.isfinite(v) for v in vals) and any(abs(v) > 1e-6 for v in vals):
            return 'green'
    return 'red'


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def _write_results(payload: dict, path: Path) -> None:
    with open(path, 'w') as f:
        json.dump(payload, f, indent=2, default=str)
    print(f'wrote {path}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=('toy', 'texas2k', 'both'), default='toy')
    ap.add_argument('--run-id', default='v1')
    args = ap.parse_args()

    summary: dict[str, str] = {}

    if args.mode in ('toy', 'both'):
        out = run_toy()
        _write_results(out, BASE_DIR / f'spike_results_{args.run_id}_toy.json')
        summary['toy'] = out['verdict']

    if args.mode in ('texas2k', 'both'):
        out = run_texas2k()
        _write_results(out, BASE_DIR / f'spike_results_{args.run_id}_texas2k.json')
        summary['texas2k'] = out['verdict']

    print('\n' + '=' * 50)
    for mode, verdict in summary.items():
        print(f'  {mode}: {verdict.upper()}')
    print('=' * 50)


if __name__ == '__main__':
    main()
