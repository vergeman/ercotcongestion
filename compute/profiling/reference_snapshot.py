"""
Smoke test for the operating data adapter + compute_snapshot.

Loads a fresh network, builds operating data for a single timestamp,
runs the OPF, and prints the result. Reproducible from a clean state
every run.

Usage:
    docker compose run --rm compute python /compute/profiling/reference_snapshot.py
    docker compose run --rm compute python /compute/profiling/reference_snapshot.py --run-id line_derate1

"""
import sys
sys.path.insert(0, '/compute')

import json
from pathlib import Path
from itertools import chain
import argparse
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

BASE_DIR = Path(__file__).parent
REF_FILE = BASE_DIR / "reference_dates.json"
RESULTS_FILE = BASE_DIR / "reference_snapshots.json"



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        '--run-id',
        default="test",
        help="Identifier for this experiment (e.g., 'baseline', 'derate_L3704')"
    )
    args = ap.parse_args()


    # load dates
    with open(REF_FILE, 'r') as f:
        refs = json.load(f)

    results = []
    for regime, timestamps in refs.items():

        res = {
          "regime": regime,
          "run_id": args.run_id
        }

        for _ts in timestamps:
            # _ts = "2026-03-25T22:00"  # NB: need data (stub for data)
            ts = datetime.fromisoformat(_ts).replace(tzinfo=timezone.utc)
            _, _, _, output_data = run(ts)
            res.update(output_data)

        results.append(res)

    with open(RESULTS_FILE, 'w') as f:
        json.dump(results, f)


def run(ts):

    #ts = datetime.fromisoformat(input_ts).replace(tzinfo=timezone.utc)

    # Reference data
    mc = pd.read_csv(MARGINAL_COSTS_CSV, index_col=0)
    bus_weather_zones = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    gen_enriched = pd.read_csv(GENERATOR_MATCHES_ENRICHED_CSV)

    # Adapter
    n_init = pypsa.Network(NETWORK_NC) # network for static precomputation
    conn = psycopg.connect(PG_DSN)

    adapter = OperatingDataAdapter(conn, gen_enriched, bus_weather_zones, n_init)

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

    output_data = {
      "total_load_mw": m['total_load_mw'],
      "total_gen_mw": m['total_gen_mw'],
      "objective_cost": m['objective_cost'],
      "lmps": {
        "min": m['lmp_min'],
        "max": m['lmp_max'],
        "mean": m['lmp_mean']
      },
      "n_binding_lines": m['n_binding_lines'],
      "fragility_total": m['fragility_total'],
      "fragility_top10_share": m['fragility_top10_share'],
      "top_10_fragile_buses": result['fragility'].nlargest(10).round(3).to_dict(),
      "top_5_binding_lines": result['shadow_prices'].head(5).round(2).to_dict() if not result['shadow_prices'].empty else {}
}
    return result, op, n, output_data

if __name__ == '__main__':
    main()
