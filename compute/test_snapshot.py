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
import logging
import os
from datetime import datetime, timezone

import pandas as pd
import psycopg
import pypsa

from config import (
    PG_DSN, NETWORK_NC,
    MARGINAL_COSTS_CSV, BUS_WEATHER_LOAD_ZONES_CSV, GENERATOR_MATCHES_ENRICHED_CSV
)
from operating_data_adapter import OperatingDataAdapter
from snapshot import run_snapshot_for_ts
from _timing import timed



def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
    )
    for noisy in ('pypsa', 'linopy', 'highspy', 'pypsa.consistency',
                  'pypsa.optimization', 'pypsa.optimization.optimize',
                  'pypsa.network.io'):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    ap = argparse.ArgumentParser()
    ap.add_argument(
        '--ts',
        default='2026-03-25T22:00',
        help='UTC timestamp, ISO format (e.g. 2026-04-22T18:00)',
    )
    args = ap.parse_args()

    ts = datetime.fromisoformat(args.ts).replace(tzinfo=timezone.utc)

    # Reference data
    with timed("setup.read_csv.marginal_costs"):
        mc = pd.read_csv(MARGINAL_COSTS_CSV, index_col=0)
    with timed("setup.read_csv.bus_weather_zones"):
        bus_weather_zones = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    with timed("setup.read_csv.gen_enriched"):
        gen_enriched = pd.read_csv(GENERATOR_MATCHES_ENRICHED_CSV)

    # Adapter
    with timed("setup.load_network_init"):
        n_init = pypsa.Network(NETWORK_NC) # network for static precomputation
    with timed("setup.pg_connect"):
        conn = psycopg.connect(PG_DSN)

    with timed("setup.adapter_init"):
        adapter = OperatingDataAdapter(conn, gen_enriched, bus_weather_zones, n_init)

    with timed("run_snapshot_for_ts"):
        result, op, n = run_snapshot_for_ts(ts, adapter, mc)

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
    print(f"Fragility total: {m['fragility_total']:.2f}")
    print(f"Top 10 share:    {m['fragility_top10_share']:.1%}")
    print(f"\nTop 10 fragile buses:")
    print(result['fragility'].nlargest(10).round(3).to_string())

    if not result['shadow_prices'].empty:
        print(f"\nTop 5 binding lines:")
        print(result['shadow_prices'].head(5).round(2).to_string())

    return result, op, n

if __name__ == '__main__':
    result, op, n = main()
