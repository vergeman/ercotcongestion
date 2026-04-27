"""
Smoke test for the operating data adapter + compute_snapshot.

Loads a fresh network, builds operating data for a single timestamp,
runs the OPF, and prints the result. Reproducible from a clean state
every run.

Usage:
    docker compose run --rm app python scripts/test_snapshot.py
    docker compose run --rm app python scripts/test_snapshot.py --ts 2026-04-22T18:00
"""
import argparse
import os
from datetime import datetime, timezone

import pandas as pd
import psycopg
import pypsa

from operating_data_adapter import OperatingDataAdapter
from snapshot import compute_snapshot


PG_DSN = (
    f"host={os.environ['PG_HOST']} port={os.environ['PG_PORT']} "
    f"dbname={os.environ['PG_DATABASE']} "
    f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}"
)

NETWORK_PATH = "/data/processed/Texas2k_series25_case1_summerpeak.nc"
MARGINAL_COSTS_PATH = "/data/processed/marginal_costs.csv"
BUS_ZONES_PATH = "/data/processed/bus_zones.csv"
GEN_ENRICHED_PATH = "/data/processed/generator_matches_enriched.csv"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        '--ts',
        default='2026-03-25T22:00',
        help='UTC timestamp, ISO format (e.g. 2026-04-22T18:00)',
    )
    args = ap.parse_args()

    ts = datetime.fromisoformat(args.ts).replace(tzinfo=timezone.utc)

    # Load network fresh
    n = pypsa.Network(NETWORK_PATH)
    mc = pd.read_csv(MARGINAL_COSTS_PATH, index_col=0)
    n.generators['marginal_cost'] = n.generators.index.map(mc['marginal_cost']).fillna(0)

    # Reference data
    bus_zones = pd.read_csv(BUS_ZONES_PATH)
    gen_enriched = pd.read_csv(GEN_ENRICHED_PATH)

    # Adapter
    conn = psycopg.connect(PG_DSN)
    adapter = OperatingDataAdapter(conn, gen_enriched, bus_zones, n)

    # Build operating data
    op = adapter.build(ts)

    # Run OPF
    result = compute_snapshot(n, op)

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


if __name__ == '__main__':
    main()
