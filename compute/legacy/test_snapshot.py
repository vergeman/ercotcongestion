"""
Smoke test for the operating data adapter + compute_snapshot.

Loads a fresh network, builds operating data for a single timestamp,
runs the OPF, and prints the result. Reproducible from a clean state
every run.

Usage:
    docker compose run --rm compute python /compute/test_snapshot.py
    docker compose run --rm compute python /compute/test_snapshot.py --ts 2026-04-22T18:00
"""
import argparse
import os
from datetime import datetime, timezone

import pandas as pd
import psycopg
import pypsa

from config import (
    PG_DSN, NETWORK_NC,
    MARGINAL_COSTS_CSV, BUS_WEATHER_LOAD_ZONES_CSV, GENERATOR_MATCHES_ENRICHED_CSV
)
from compute.legacy.operating_conditions import apply_static_mutations
from compute.legacy.operating_data_adapter import OperatingDataAdapter
from compute.legacy.snapshot import compute_snapshot_batch



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        '--ts',
        default='2026-03-25T22:00',
        help='UTC timestamp, ISO format (e.g. 2026-04-22T18:00)',
    )
    args = ap.parse_args()

    ts = datetime.fromisoformat(args.ts).replace(tzinfo=timezone.utc)

    # Reference data
    mc = pd.read_csv(MARGINAL_COSTS_CSV, index_col=0)
    bus_weather_zones = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    gen_enriched = pd.read_csv(GENERATOR_MATCHES_ENRICHED_CSV)

    # Network + adapter
    n = pypsa.Network(NETWORK_NC)
    n.generators['marginal_cost'] = (
        n.generators.index.map(mc['marginal_cost']).fillna(0)
    )
    conn = psycopg.connect(PG_DSN)
    adapter = OperatingDataAdapter(conn, gen_enriched, bus_weather_zones, n)
    apply_static_mutations(
        n, line_derate=adapter.line_derate, tx_derate=adapter.tx_derate,
    )

    op = adapter.build(ts)
    results = compute_snapshot_batch(
        n, [ts], {ts: op}, enable_diagnostics=True,
    )
    result = results[ts]

    # Report
    print(f"\n{'=' * 60}")
    print(f"Snapshot for {ts.isoformat()}")
    print(f"{'=' * 60}")
    print(f"Status: {result['status']}")

    if result['status'] != 'ok':
        return

    m = result['meta']
    print(f"Load:  {m['total_load_mw']:>10,.0f} MW")
    print(f"Gen:   {m['total_gen_mw']:>10,.0f} MW")
    print(f"Cost:  ${m['objective_cost']:>10,.0f}")
    print(f"LMPs:  ${m['lmp_min']:.2f} – ${m['lmp_max']:.2f}  (mean ${m['lmp_mean']:.2f})")
    print(f"Binding lines: {m['n_binding_lines']}")
    print(f"modeled_congestion: total={m['modeled_congestion_total']:+.2f}  "
          f"|total|={m['modeled_congestion_abs_total']:.2f}  "
          f"top10 |share|={m['modeled_congestion_top10_share']:.1%}")
    bp_max = m['binding_proximity_max']
    bp_p95 = m['binding_proximity_p95']
    print(f"binding_proximity:  max={bp_max if bp_max is None else f'{bp_max:.3f}'}  "
          f"p95={bp_p95 if bp_p95 is None else f'{bp_p95:.3f}'}")

    mc = result['modeled_congestion']
    bp = result['binding_proximity']
    print(f"\nTop 10 buses by |modeled_congestion| (signed):")
    print(mc.reindex(mc.abs().nlargest(10).index).round(3).to_string())
    print(f"\nTop 10 buses by binding_proximity:")
    print(bp.nlargest(10).round(3).to_string())

    if not result['shadow_prices'].empty:
        print(f"\nTop 5 binding lines:")
        print(result['shadow_prices'].head(5).round(2).to_string())

    # Smoke assertions — structural checks, not a full sign-convention proof
    # (that lives in verify_sign_convention.py).
    assert 'modeled_congestion' in result and 'binding_proximity' in result
    assert mc.dtype.kind == 'f'
    assert (bp.dropna() >= 0).all()
    # Sign check: when any lines bind, modeled_congestion must retain sign
    # information — PTDF has both signs across the bus population, so
    # Σ PTDF·μ_signed should not collapse to a single-signed vector. If this
    # ever fires, someone has re-introduced .abs() or squared PTDF upstream.
    if m['n_binding_lines'] > 0 and mc.abs().sum() > 0:
        assert (mc > 0).any() and (mc < 0).any(), (
            "modeled_congestion has only one sign despite binding lines — "
            "check congestion.modeled_congestion_at for lost sign information"
        )

    return result, op, n

if __name__ == '__main__':
    main()
