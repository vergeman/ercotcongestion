"""
Sprint 3 analysis: consume derate_sweep.py CSVs and answer the two questions.

    (a) Rank stability. Is the spatial ranking of congested buses stable
        across the derate axis within each snapshot? Metrics:
          - Pairwise Jaccard overlap of top-K bus sets (by |signed MC|)
          - Spearman ρ on |MC| rank vectors
        Aggregated: mean/median across snapshots. Reported per adjacent pair
        and against the baseline derate.

    (b) Basis calibration. Which derate best matches signed observed basis?
        Per (ts, derate): Spearman ρ(signed modeled_congestion, signed basis)
        restricted to buses with basis data. Aggregated across snapshots →
        which derate wins on median ρ?

    (c) Feasibility rate per derate — from the snapshot_summary.csv.

Usage::

    docker compose run --rm compute python /compute/derate_sweep/derate_sweep_analysis.py \
        [--in /compute/derate_sweep/results] \
        [--top-k 20] \
        [--baseline-line-derate 0.90]
"""
from __future__ import annotations

import argparse
import logging
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)
log = logging.getLogger('derate_sweep_analysis')

DEFAULT_IN = Path('/compute/derate_sweep/results')
BASELINE_LINE_DERATE = 0.90  # current production value; comparison anchor


def _load(in_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    summary = pd.read_csv(in_dir / 'snapshot_summary.csv')
    bus = pd.read_csv(in_dir / 'bus_metrics.csv')
    return summary, bus


# ---------------------------------------------------------------------------
# (c) Feasibility rate
# ---------------------------------------------------------------------------
def report_feasibility(summary: pd.DataFrame) -> pd.DataFrame:
    grouped = summary.groupby(['line_derate', 'tx_derate']).agg(
        n_snapshots=('status', 'size'),
        n_ok=('status', lambda s: (s == 'ok').sum()),
    )
    grouped['feasibility_rate'] = grouped['n_ok'] / grouped['n_snapshots']
    print('\n=== Feasibility rate by derate ===')
    print(grouped.to_string())
    return grouped.reset_index()


# ---------------------------------------------------------------------------
# (a) Rank stability across derate levels, per snapshot
# ---------------------------------------------------------------------------
def _top_k_bus_set(bus_df: pd.DataFrame, k: int) -> set[str]:
    """Return the top-K bus ids by |modeled_congestion|."""
    return set(
        bus_df.assign(mc_abs=bus_df['modeled_congestion'].abs())
              .nlargest(k, 'mc_abs')['bus_id']
              .astype(str)
              .tolist()
    )


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return float('nan')
    return len(a & b) / len(a | b)


def rank_stability(bus: pd.DataFrame, top_k: int) -> pd.DataFrame:
    """Per snapshot: pairwise Jaccard of top-K sets + Spearman on full |MC|
    rank vectors, across every ordered pair of derate configs."""
    rows: list[dict] = []
    for ts, ts_frame in bus.groupby('ts'):
        derate_frames = {
            (float(ld), float(td)): sub
            for (ld, td), sub in ts_frame.groupby(['line_derate', 'tx_derate'])
        }
        derate_keys = sorted(derate_frames.keys())
        for a_key, b_key in combinations(derate_keys, 2):
            a = derate_frames[a_key].set_index('bus_id')['modeled_congestion']
            b = derate_frames[b_key].set_index('bus_id')['modeled_congestion']
            shared = a.index.intersection(b.index)
            if len(shared) == 0:
                continue
            jac = _jaccard(
                _top_k_bus_set(derate_frames[a_key], top_k),
                _top_k_bus_set(derate_frames[b_key], top_k),
            )
            rho, _p = spearmanr(a.loc[shared].abs(), b.loc[shared].abs())
            rows.append({
                'ts': ts,
                'derate_a': a_key, 'derate_b': b_key,
                'jaccard_top_k': jac,
                'spearman_abs_mc': rho,
            })

    df = pd.DataFrame(rows)
    if df.empty:
        log.warning('rank_stability: no derate pairs to compare (need ≥2 feasible per snapshot)')
        return df

    agg = df.groupby(['derate_a', 'derate_b']).agg(
        n=('jaccard_top_k', 'size'),
        jaccard_mean=('jaccard_top_k', 'mean'),
        jaccard_median=('jaccard_top_k', 'median'),
        spearman_mean=('spearman_abs_mc', 'mean'),
        spearman_median=('spearman_abs_mc', 'median'),
    )
    print(f'\n=== Rank stability (top-{top_k} Jaccard + Spearman on |MC|) ===')
    print(agg.round(3).to_string())
    return df


# ---------------------------------------------------------------------------
# (b) Basis calibration
# ---------------------------------------------------------------------------
def basis_calibration(bus: pd.DataFrame) -> pd.DataFrame:
    """Per (ts, derate): Spearman ρ between signed MC and signed basis over
    buses with basis data. Aggregate median/mean across ts per derate."""
    rows: list[dict] = []
    for (ts, ld, td), sub in bus.groupby(['ts', 'line_derate', 'tx_derate']):
        pair = sub[['modeled_congestion', 'basis']].dropna()
        if len(pair) < 10:
            continue
        rho, p = spearmanr(pair['modeled_congestion'], pair['basis'])
        rows.append({
            'ts': ts, 'line_derate': float(ld), 'tx_derate': float(td),
            'n': len(pair),
            'spearman_mc_vs_basis': rho,
            'p_value': p,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        log.warning('basis_calibration: no (ts, derate) with basis data')
        return df

    agg = df.groupby(['line_derate', 'tx_derate']).agg(
        n_ts=('ts', 'nunique'),
        rho_mean=('spearman_mc_vs_basis', 'mean'),
        rho_median=('spearman_mc_vs_basis', 'median'),
    ).sort_values('rho_median', ascending=False)
    print('\n=== Basis calibration (Spearman signed MC vs signed basis) ===')
    print(agg.round(3).to_string())

    best = agg['rho_median'].idxmax()
    print(f'\nBest-fit derate by median ρ: line={best[0]:.2f}, tx={best[1]:.2f} '
          f'(median ρ = {agg.loc[best, "rho_median"]:.3f})')
    return df


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------
def run(in_dir: Path, top_k: int) -> None:
    summary, bus = _load(in_dir)
    log.info(f'loaded {len(summary)} summary rows, {len(bus)} bus-level rows')

    report_feasibility(summary)
    rank_stability(bus, top_k)
    basis_calibration(bus)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split('\n\n', 1)[0])
    p.add_argument('--in', dest='in_dir', type=Path, default=DEFAULT_IN)
    p.add_argument('--top-k', type=int, default=20)
    return p.parse_args()


if __name__ == '__main__':
    args = _parse_args()
    run(args.in_dir, args.top_k)
