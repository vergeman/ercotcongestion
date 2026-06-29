"""
Option 4: KKT reconstruction of system λ.

Runs the existing vanilla DC OPF (no extra constraints), then post-processes
the LMPs + line/transformer shadow prices + PTDF to recover λ̂ per bus. If
the decomposition is consistent, λ̂ is the same across all buses and the
residual norm is near machine epsilon.

Usage:
  docker compose run --rm compute python \\
      /compute/experiments/system_lambda/kkt_reconstruct.py --mode both --run-id v1
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

from ptdf_lodf import get_ptdf_lodf
from kkt import reconstruct_lambda
from spike_extract import build_toy_network, TOY_SNAPSHOTS, _prepare_texas2k

BASE_DIR = Path(__file__).parent
SOLVER = 'highs'


def _solve_vanilla(n: pypsa.Network) -> dict:
    """Standard DC OPF, matches production. Returns extracted quantities for
    a single snapshot."""
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
    line_mu_up = _slice(n.lines_t.mu_upper,        ts, w)
    line_mu_lo = _slice(n.lines_t.mu_lower,        ts, w)
    tx_mu_up   = _slice(n.transformers_t.mu_upper, ts, w)
    tx_mu_lo   = _slice(n.transformers_t.mu_lower, ts, w)

    # Generator dispatch + duals for clean-bus identification.
    gen_p      = n.generators_t.p.loc[ts]
    gen_mu_up  = _slice(n.generators_t.mu_upper, ts, w)
    gen_mu_lo  = _slice(n.generators_t.mu_lower, ts, w)

    ptdf, _lodf, bus_names = get_ptdf_lodf(n)
    return {
        'status':      'ok',
        'lmps':        lmps,
        'line_mu_up':  line_mu_up,
        'line_mu_lo':  line_mu_lo,
        'tx_mu_up':    tx_mu_up,
        'tx_mu_lo':    tx_mu_lo,
        'gen_p':       gen_p,
        'gen_mu_up':   gen_mu_up,
        'gen_mu_lo':   gen_mu_lo,
        'gen_bus':     n.generators['bus'],
        'ptdf':        ptdf,
        'bus_names':   bus_names,
        'line_names':  list(n.lines.index),
        'tx_names':    list(n.transformers.index),
    }


def _clean_bus_set(res: dict, dual_tol: float = 1e-6, p_tol: float = 1e-3) -> list:
    """Buses with at least one dispatching unbound generator.

    Unbound means both upper and lower duals near zero (within `dual_tol`).
    Dispatching means p > p_tol. At such a bus, λ̂_i = c_g (the system
    marginal cost) exactly, with no scarcity-rent contamination.
    """
    gen_p     = res['gen_p']
    gen_mu_up = res['gen_mu_up']
    gen_mu_lo = res['gen_mu_lo']
    gen_bus   = res['gen_bus']
    if gen_mu_up is None or gen_mu_lo is None:
        return []
    unbound = (gen_mu_up.abs() < dual_tol) & (gen_mu_lo.abs() < dual_tol)
    dispatching = gen_p > p_tol
    eligible_gens = gen_p.index[unbound & dispatching]
    return sorted(set(gen_bus.loc[eligible_gens]))


def _slice(df: pd.DataFrame, ts, w: pd.Series) -> pd.Series | None:
    if df is None or df.empty:
        return None
    # Mirror production divide-by-weighting for dual values per snapshot.
    return df.divide(w, axis=0).loc[ts]


# ---------------------------------------------------------------------------
# Mode: toy
# ---------------------------------------------------------------------------

def run_toy() -> dict:
    records = []
    for snap in TOY_SNAPSHOTS:
        rec: dict = {
            'snapshot_id':     snap.snapshot_id,
            'expected_lambda': snap.expected_lambda,
            'notes':           snap.notes,
        }
        try:
            n = build_toy_network(snap)
            res = _solve_vanilla(n)
            rec['solver_status'] = res['status']
            if res['status'] != 'ok':
                rec['error'] = res.get('condition')
                records.append(rec)
                continue

            tx_names = res['tx_names'] if res['tx_names'] else None
            kkt = reconstruct_lambda(
                lmps=res['lmps'],
                line_mu_upper=res['line_mu_up'],
                line_mu_lower=res['line_mu_lo'],
                tx_mu_upper=res['tx_mu_up'],
                tx_mu_lower=res['tx_mu_lo'],
                ptdf=res['ptdf'],
                bus_names=res['bus_names'],
                line_names=res['line_names'],
                tx_names=tx_names,
            )
            rec['lambda_hat']         = kkt['lambda_hat']
            rec['lambda_hat_per_bus'] = {b: float(v)
                                         for b, v in kkt['lambda_hat_per_bus'].items()}
            rec['residual_norm']      = kkt['residual_norm']
            rec['residual_max']       = kkt['residual_max']
            rec['lmps']               = {b: float(v) for b, v in res['lmps'].items()}
            rec['line_mu_upper']      = {l: float(v)
                                         for l, v in res['line_mu_up'].items()} if res['line_mu_up'] is not None else {}
            rec['line_mu_lower']      = {l: float(v)
                                         for l, v in res['line_mu_lo'].items()} if res['line_mu_lo'] is not None else {}
            if snap.expected_lambda is not None:
                rec['lambda_abs_diff'] = abs(kkt['lambda_hat'] - snap.expected_lambda)
        except Exception as e:
            traceback.print_exc()
            rec['error'] = f'{type(e).__name__}: {e}'
        records.append(rec)
    return {'mode': 'toy', 'records': records, 'verdict': _verdict(records, tol=1e-3)}


# ---------------------------------------------------------------------------
# Mode: texas2k
# ---------------------------------------------------------------------------

def run_texas2k() -> dict:
    n = _prepare_texas2k()
    rec: dict = {
        'snapshot_id':   'texas2k_static',
        'n_buses':       int(len(n.buses)),
        'n_generators':  int(len(n.generators)),
        'n_loads':       int(len(n.loads)),
        'n_lines':       int(len(n.lines)),
        'n_transformers': int(len(n.transformers)),
        'total_load_mw': float(n.loads['p_set'].sum()),
    }
    try:
        res = _solve_vanilla(n)
        rec['solver_status'] = res['status']
        if res['status'] != 'ok':
            rec['error'] = res.get('condition')
            return {'mode': 'texas2k', 'records': [rec], 'verdict': 'red'}

        tx_names = res['tx_names'] if res['tx_names'] else None
        kkt = reconstruct_lambda(
            lmps=res['lmps'],
            line_mu_upper=res['line_mu_up'],
            line_mu_lower=res['line_mu_lo'],
            tx_mu_upper=res['tx_mu_up'],
            tx_mu_lower=res['tx_mu_lo'],
            ptdf=res['ptdf'],
            bus_names=res['bus_names'],
            line_names=res['line_names'],
            tx_names=tx_names,
        )

        lmps_clean = res['lmps'].dropna()
        lh_all = kkt['lambda_hat_per_bus'].dropna()

        # LMP == 0 exactly = LP-degenerate radial/dead-end bus (no gen, no
        # load): LMP is undetermined and HiGHS defaults to 0. Filter these
        # out — they have no economic interpretation.
        nontrivial = lmps_clean.abs() > 1e-9
        lh = lh_all.reindex(nontrivial[nontrivial].index)

        # CLEAN-BUS SET: buses with ≥1 dispatching unbound generator. At
        # these buses, λ̂_i = c_g exactly (no scarcity rent). The median
        # over this set is the principled system marginal cost.
        clean_buses = _clean_bus_set(res)
        clean_idx = lh.index.intersection(clean_buses)
        lh_clean = lh.reindex(clean_idx)

        if len(lh_clean) > 0:
            lambda_hat_clean_median = float(lh_clean.median())
            clean_dist = {
                'n':   int(len(lh_clean)),
                'p5':  float(lh_clean.quantile(0.05)),
                'p50': float(lh_clean.median()),
                'p95': float(lh_clean.quantile(0.95)),
                'min': float(lh_clean.min()),
                'max': float(lh_clean.max()),
            }
            resid_clean = (lh_clean - lambda_hat_clean_median).abs()
            clean_resid = {
                'p50': float(resid_clean.median()),
                'p95': float(resid_clean.quantile(0.95)),
                'max': float(resid_clean.max()),
            }
        else:
            lambda_hat_clean_median = float('nan')
            clean_dist = {'n': 0}
            clean_resid = {'p50': float('nan'), 'p95': float('nan'), 'max': float('nan')}

        # Comparators (no editorial framing).
        load_per_bus = (
            n.loads.groupby('bus')['p_set'].sum()
            .reindex(lh.index).fillna(0.0)
        )
        load_total = float(load_per_bus.sum())
        lw = float((lh * load_per_bus).sum() / load_total) if load_total > 0 else float('nan')

        rec.update({
            # PRIMARY
            'lambda_hat_clean_median':     lambda_hat_clean_median,
            'clean_bus_distribution':      clean_dist,
            'clean_bus_residual_vs_median': clean_resid,
            # COMPARATORS (diagnostic only)
            'lambda_hat_load_weighted':    lw,
            'lambda_hat_filtered_median':  float(lh.median()),
            'lmp_median':                  float(lmps_clean.median()),
            # FULL-BUS DISTRIBUTION (context)
            'filtered_bus_distribution': {
                'n':   int(len(lh)),
                'p5':  float(lh.quantile(0.05)),
                'p50': float(lh.median()),
                'p95': float(lh.quantile(0.95)),
                'min': float(lh.min()),
                'max': float(lh.max()),
            },
            'n_buses_total':            int(len(lh_all)),
            'n_buses_lmp_degenerate':   int(len(lh_all) - len(lh)),
            'n_buses_clean':            int(len(lh_clean)),
            # Raw (unfiltered) stats kept for sanity.
            'raw_residual_norm':        kkt['residual_norm'],
            'raw_residual_max':         kkt['residual_max'],
        })
    except Exception as e:
        traceback.print_exc()
        rec['error'] = f'{type(e).__name__}: {e}'

    return {'mode': 'texas2k', 'records': [rec], 'verdict': _verdict_texas2k(rec)}


def _verdict(records: list[dict], tol: float) -> str:
    """Toy: green if all residual_max < tol."""
    for r in records:
        if 'error' in r or 'residual_max' not in r:
            return 'red'
    if all(r['residual_max'] < tol for r in records):
        return 'green'
    if np.median([r['residual_max'] for r in records]) < tol:
        return 'yellow'
    return 'red'


def _verdict_texas2k(rec: dict) -> str:
    """Verdict on the CLEAN-BUS distribution (buses with ≥1 unbound
    dispatching gen, where λ̂_i should equal c_g exactly).

      green:  clean p95 < $1   — decomposition closes on the principled set
      yellow: clean p50 < $5   — center holds, tail residual remains
      red:    otherwise, or zero clean buses, or solver error"""
    if 'error' in rec:
        return 'red'
    r = rec.get('clean_bus_residual_vs_median', {})
    if not r or rec.get('n_buses_clean', 0) == 0:
        return 'red'
    p95 = r.get('p95', float('inf'))
    p50 = r.get('p50', float('inf'))
    if p95 < 1.0:
        return 'green'
    if p50 < 5.0:
        return 'yellow'
    return 'red'


def _write(payload: dict, path: Path) -> None:
    with open(path, 'w') as f:
        json.dump(payload, f, indent=2, default=str)
    print(f'wrote {path}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=('toy', 'texas2k', 'both'), default='both')
    ap.add_argument('--run-id', default='v1')
    args = ap.parse_args()

    summary: dict[str, str] = {}
    if args.mode in ('toy', 'both'):
        out = run_toy()
        _write(out, BASE_DIR / f'kkt_results_{args.run_id}_toy.json')
        summary['toy'] = out['verdict']
    if args.mode in ('texas2k', 'both'):
        out = run_texas2k()
        _write(out, BASE_DIR / f'kkt_results_{args.run_id}_texas2k.json')
        summary['texas2k'] = out['verdict']

    print('\n' + '=' * 50)
    for mode, v in summary.items():
        print(f'  {mode}: {v.upper()}')
    print('=' * 50)


if __name__ == '__main__':
    main()
