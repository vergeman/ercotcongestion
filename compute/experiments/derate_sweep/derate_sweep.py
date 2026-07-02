"""
Sprint 3 harness: derate sensitivity sweep across the Sprint-0 snapshot sample.

Sweeps a tied (line_derate, tx_derate) axis for each reference snapshot,
solves the OPF, computes signed modeled_congestion + binding_proximity, and
persists two long-form CSVs for downstream analysis:

    snapshot_summary.csv  — one row per (ts, derate): solve status, meta stats
    bus_metrics.csv       — one row per (ts, derate, bus): mc, bp, basis

Analysis (rank stability + basis calibration) lives in derate_sweep_analysis.py.

Usage (docker compose)::

    docker compose run --rm compute python /compute/experiments/derate_sweep/derate_sweep.py \
        [--sample /compute/sample_specs/reference_dates.json] \
        [--out /compute/experiments/derate_sweep/results]

Design notes:
- Zonal load scaling (Sprint 1) is preserved. Derate is applied on top of the
  already-scaled loads. Adapter static metadata is derate-independent, so we
  build op once per ts and override op['line_derate']/op['tx_derate'] per
  sweep point instead of re-instantiating the adapter.
- On solve infeasibility at a given derate the row is recorded with
  status='infeasible' — an expected, reportable finding per Sprint 3 spec.
- Uses the single-snapshot solve path (apply_operating_conditions +
  n.optimize) rather than compute_snapshot_batch; simpler to reason about
  and matches the compare_zonal_lmp.py experiment precedent.
"""
from __future__ import annotations

import sys
sys.path.insert(0, '/compute')

import argparse
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg
import pypsa

from config import (
    PG_DSN, NETWORK_NC, MARGINAL_COSTS_CSV,
    BUS_WEATHER_LOAD_ZONES_CSV, GENERATOR_MATCHES_ENRICHED_CSV,
)
from congestion import modeled_congestion_at, binding_proximity_at
from operating_conditions import apply_operating_conditions
from operating_data_adapter import OperatingDataAdapter
from ptdf_lodf import get_ptdf_lodf
from snapshot import _compute_basis

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)
log = logging.getLogger('derate_sweep')


# Tied (line, tx) axis per Sprint 3 spec: transformers always slightly looser,
# 5 points from unity down toward the feasibility edge. 0.70 is known infeasible
# at 86 GW load, so 0.80 anchors the lower end for the sweep (rank-stability
# window). Baseline production is 0.90/0.95 for reference.
DERATE_AXIS: list[tuple[float, float]] = [
    (1.00, 1.00),
    (0.95, 0.97),
    (0.90, 0.95),
    (0.85, 0.90),
    (0.80, 0.85),
]

DEFAULT_SAMPLE = Path('/compute/sample_specs/reference_dates.json')
DEFAULT_OUT = Path('/compute/experiments/derate_sweep/results')
SHED_COST = 5000.0
SHED_PREFIX = 'shed_'


def _load_sample(path: Path) -> list[tuple[str, datetime]]:
    """Return [(regime, ts_utc), ...] flattened from the sample json."""
    payload = json.loads(path.read_text())
    out: list[tuple[str, datetime]] = []
    for regime, tss in payload.items():
        for raw in tss:
            ts = datetime.fromisoformat(raw).astimezone(timezone.utc)
            out.append((regime, ts))
    return out


def _fresh_network(mc: pd.DataFrame) -> pypsa.Network:
    n = pypsa.Network(NETWORK_NC)
    n.generators['marginal_cost'] = (
        n.generators.index.map(mc['marginal_cost']).fillna(0)
    )
    return n


def _add_load_shed(n: pypsa.Network) -> None:
    """Per-bus load-shed backstop so the sweep records congestion outcomes
    rather than infeasibility from marginal load imbalance. Mirrors the shape
    used in compute_snapshot_batch and compare_zonal_lmp.py."""
    p_nom = float(n.loads['p_set'].sum())
    n.add(
        'Generator',
        [f'{SHED_PREFIX}{b}' for b in n.buses.index],
        bus=n.buses.index.values,
        carrier='load_shed',
        marginal_cost=SHED_COST,
        p_nom=p_nom,
        p_nom_extendable=False,
    )


def _solve(n: pypsa.Network) -> tuple[str, str]:
    n.optimize.create_model()
    status, condition = n.model.solve(solver_name='highs', io_api='direct')
    if status == 'ok':
        n.optimize.assign_solution()
        n.optimize.assign_duals(assign_all_duals=True)
    return status, condition


def _snapshot_slice(df: pd.DataFrame) -> pd.Series | None:
    if df is None or df.empty:
        return None
    return df.iloc[0]


def _compute_point(
    ts: datetime,
    regime: str,
    line_d: float,
    tx_d: float,
    op: dict,
    mc: pd.DataFrame,
) -> tuple[dict, pd.DataFrame | None]:
    """Solve one (ts, derate) point. Return (summary_row, bus_rows|None)."""
    n = _fresh_network(mc)

    # Override the adapter's derate on the op dict — apply_operating_conditions
    # reads these via **op and passes to apply_static_mutations.
    op_derated = dict(op)
    op_derated['line_derate'] = line_d
    op_derated['tx_derate'] = tx_d
    apply_operating_conditions(n, **op_derated)
    _add_load_shed(n)

    t0 = time.perf_counter()
    status, condition = _solve(n)
    solve_s = time.perf_counter() - t0

    base_row = {
        'ts': ts.isoformat(),
        'regime': regime,
        'line_derate': line_d,
        'tx_derate': tx_d,
        'status': 'ok' if status == 'ok' else 'infeasible',
        'condition': condition,
        'solve_s': round(solve_s, 3),
        'load_scaling_mode': op['meta'].get('load_scaling_mode'),
        'total_load_mw': float(op['meta'].get('load_total_mw') or 0.0),
    }

    if status != 'ok':
        log.warning(
            f'{ts.isoformat()} derate=({line_d:.2f},{tx_d:.2f}) '
            f'infeasible: {condition}'
        )
        base_row.update({
            'n_binding_lines': None, 'mc_abs_total': None,
            'mc_top10_abs_share': None, 'bp_max': None, 'bp_p95': None,
            'basis_n': None, 'basis_abs_mean': None, 'load_shed_mw': None,
        })
        return base_row, None

    # Post-processing on the solved snapshot.
    w = n.snapshot_weightings.objective
    n.buses_t.marginal_price = n.buses_t.marginal_price.divide(w, axis=0)

    ptdf_full, _lodf, bus_names = get_ptdf_lodf(n)
    mc_series = modeled_congestion_at(
        n,
        _snapshot_slice(n.lines_t.mu_upper),
        _snapshot_slice(n.lines_t.mu_lower),
        _snapshot_slice(n.transformers_t.mu_upper),
        _snapshot_slice(n.transformers_t.mu_lower),
        ptdf_full, bus_names,
    )
    bp_series = binding_proximity_at(
        n,
        _snapshot_slice(n.lines_t.p0),
        _snapshot_slice(n.transformers_t.p0),
        _snapshot_slice(n.lines_t.s_max_pu),
        _snapshot_slice(n.transformers_t.s_max_pu),
        ptdf_full, bus_names,
    )

    lmps = n.buses_t.marginal_price.iloc[0].copy()
    gp = n.generators_t.p.iloc[0]
    shed_mask = gp.index.str.startswith(SHED_PREFIX)
    shed_mw_series = gp[shed_mask].copy()
    shed_mw_series.index = shed_mw_series.index.str.replace(SHED_PREFIX, '', regex=False)
    shed_mw_series = shed_mw_series.reindex(n.buses.index).fillna(0.0)
    shed_buses = shed_mw_series.index[shed_mw_series > 1e-3]
    lmps.loc[shed_buses] = np.nan

    basis = _compute_basis(
        lmps,
        op.get('bus_load_zone'),
        op.get('zonal_lmp_by_zone') or {},
    )

    line_mu_up = _snapshot_slice(n.lines_t.mu_upper)
    line_mu_lo = _snapshot_slice(n.lines_t.mu_lower)
    shadow_up = line_mu_up.abs() if line_mu_up is not None else pd.Series(0.0, index=n.lines.index)
    shadow_lo = line_mu_lo.abs() if line_mu_lo is not None else pd.Series(0.0, index=n.lines.index)
    shadow = (shadow_up + shadow_lo).reindex(n.lines.index).fillna(0)
    n_binding = int((shadow > 0.01).sum())

    mc_abs = mc_series.abs()
    mc_abs_total = float(mc_abs.sum())
    top10_share = (
        float(mc_abs.nlargest(10).sum() / mc_abs_total) if mc_abs_total > 0 else 0.0
    )

    base_row.update({
        'n_binding_lines': n_binding,
        'mc_abs_total': mc_abs_total,
        'mc_top10_abs_share': top10_share,
        'bp_max': float(bp_series.max()) if bp_series.notna().any() else None,
        'bp_p95': (
            float(bp_series.quantile(0.95)) if bp_series.notna().any() else None
        ),
        'basis_n': int(basis.notna().sum()),
        'basis_abs_mean': (
            float(basis.abs().mean()) if basis.notna().any() else None
        ),
        'load_shed_mw': float(shed_mw_series.sum()),
    })

    bus_df = pd.DataFrame({
        'ts': ts.isoformat(),
        'line_derate': line_d,
        'tx_derate': tx_d,
        'bus_id': mc_series.index.astype(str),
        'modeled_congestion': mc_series.values,
        'binding_proximity': bp_series.reindex(mc_series.index).values,
        'basis': basis.reindex(mc_series.index).values,
    })
    return base_row, bus_df


def run(sample_path: Path, out_dir: Path, force_global_load_sf: bool) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / 'snapshot_summary.csv'
    bus_path = out_dir / 'bus_metrics.csv'

    sample = _load_sample(sample_path)
    log.info(
        f'sample: {len(sample)} timestamps × {len(DERATE_AXIS)} derate points '
        f'= {len(sample) * len(DERATE_AXIS)} solves'
    )

    marginal = pd.read_csv(MARGINAL_COSTS_CSV, index_col=0)
    bus_zones = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    gen_enriched = pd.read_csv(GENERATOR_MATCHES_ENRICHED_CSV)

    with psycopg.connect(PG_DSN) as conn:
        adapter = OperatingDataAdapter(
            conn, gen_enriched, bus_zones, pypsa.Network(NETWORK_NC),
        )

        summary_rows: list[dict] = []
        bus_frames: list[pd.DataFrame] = []
        for regime, ts in sample:
            try:
                op = adapter.build(ts, force_global_load_sf=force_global_load_sf)
            except Exception as e:  # noqa: BLE001 — adapter failures are per-ts
                log.warning(f'{ts.isoformat()} adapter build failed: {e}')
                for line_d, tx_d in DERATE_AXIS:
                    summary_rows.append({
                        'ts': ts.isoformat(), 'regime': regime,
                        'line_derate': line_d, 'tx_derate': tx_d,
                        'status': 'adapter_error', 'condition': str(e),
                    })
                continue

            for line_d, tx_d in DERATE_AXIS:
                row, bus_df = _compute_point(
                    ts, regime, line_d, tx_d, op, marginal,
                )
                summary_rows.append(row)
                if bus_df is not None:
                    bus_frames.append(bus_df)
                log.info(
                    f'{ts.isoformat()} derate=({line_d:.2f},{tx_d:.2f}) '
                    f'status={row["status"]} n_binding={row.get("n_binding_lines")}'
                )

    pd.DataFrame(summary_rows).to_csv(summary_path, index=False)
    log.info(f'wrote {summary_path}')

    if bus_frames:
        pd.concat(bus_frames, ignore_index=True).to_csv(bus_path, index=False)
        log.info(f'wrote {bus_path}')
    else:
        log.warning('no feasible solves — bus_metrics.csv not written')


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split('\n\n', 1)[0])
    p.add_argument('--sample', type=Path, default=DEFAULT_SAMPLE)
    p.add_argument('--out', type=Path, default=DEFAULT_OUT)
    p.add_argument(
        '--force-global-load-sf', action='store_true',
        help='Force adapter to global load scaling (skip Sprint-1 zonal). '
             'For A/B against zonal geography; sweep default is zonal.',
    )
    return p.parse_args()


if __name__ == '__main__':
    args = _parse_args()
    run(args.sample, args.out, args.force_global_load_sf)
