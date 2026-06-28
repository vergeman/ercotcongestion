"""
Phase 2 congestion snapshot.

For each reference timestamp:
  1. Run OPF via run_snapshot_for_ts (same path as profiling/reference_snapshot.py)
  2. Build inputs to compute_congestion from the model output:
       - hub_lmps: HB_BUSAVG, HB_HOUSTON, HB_NORTH, HB_SOUTH, HB_WEST →
         LMP at synthetic bus nearest each ERCOT hub centroid
         (hubs_lz_centroids.csv).
       - loads:   per-bus load aggregated from n.loads (for load_weighted ref).
       - system_lambda: median bus LMP, used as the model-side proxy for the
         energy-component price (ERCOT publishes NP6-322-CD for the real side).
  3. Compute bus-level congestion under each reference method.
  4. Persist results to JSON keyed by (regime, ts, method).

Usage:
    docker compose run --rm compute python \
        /compute/experiments/congestion_calculation/congestion_snapshot.py
    docker compose run --rm compute python \
        /compute/experiments/congestion_calculation/congestion_snapshot.py --run-id baseline
"""
import sys
from pathlib import Path

sys.path.insert(0, '/compute')
sys.path.insert(0, str(Path(__file__).parent))

import json
import argparse
import traceback
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import psycopg
import pypsa

from config import (
    PG_DSN, NETWORK_NC,
    MARGINAL_COSTS_CSV, BUS_WEATHER_LOAD_ZONES_CSV, GENERATOR_MATCHES_ENRICHED_CSV,
)
from operating_conditions import apply_static_mutations
from operating_data_adapter import OperatingDataAdapter
from snapshot import compute_snapshot_batch

from congestion import (
    compute_congestion, congestion_diagnostics, CUSTOM_HUBS, HUB_BUSAVG,
)

BASE_DIR = Path(__file__).parent
REF_FILE = Path("/compute/profiling/reference_dates.json")
HUB_CENTROIDS_CSV = Path("/data/processed/hubs_lz_centroids.csv")


def build_hub_lmps(
    lmps: pd.Series,
    n: pypsa.Network,
    hub_centroids: pd.DataFrame,
) -> dict[str, float]:
    """Map each ERCOT hub centroid to its nearest synthetic bus and read off
    that bus's LMP. Centroid-anchored (not averaged) so HB_BUSAVG stays
    distinct from load_weighted and simple_mean."""
    valid = lmps.dropna()

    bus_xy = n.buses.loc[valid.index, ['y', 'x']].rename(
        columns={'y': 'lat', 'x': 'lon'}
    ).dropna()
    bus_coords = bus_xy[['lat', 'lon']].to_numpy()
    bus_ids = bus_xy.index.to_numpy()

    hub_lmps: dict[str, float] = {}
    for hub in (HUB_BUSAVG, *CUSTOM_HUBS):
        try:
            if hub not in hub_centroids.index:
                continue
            hlat = float(hub_centroids.at[hub, 'lat'])
            hlon = float(hub_centroids.at[hub, 'lon'])
            d2 = (bus_coords[:, 0] - hlat) ** 2 + (bus_coords[:, 1] - hlon) ** 2
            nearest = bus_ids[int(np.argmin(d2))]
            hub_lmps[hub] = float(valid[nearest])
        except Exception as e:
            print(f"  build_hub_lmps[{hub}] failed: {e}")
    return hub_lmps


def build_load_per_bus(n: pypsa.Network, ts: datetime) -> pd.Series:
    """Per-bus load aggregated from the adapter-scaled time-varying loads
    written into n.loads_t.p_set for this snapshot."""
    naive_ts = pd.Timestamp(ts).tz_convert('UTC').tz_localize(None)
    load_per_load = n.loads_t.p_set.loc[naive_ts]
    return (
        load_per_load.groupby(n.loads['bus']).sum()
        .reindex(n.buses.index).fillna(0.0)
    )


def _stats(s: pd.Series) -> dict:
    s = s.dropna()
    if s.empty:
        return {}
    return {
        "mean": float(s.mean()),
        "std": float(s.std()),
        "min": float(s.min()),
        "p5": float(s.quantile(0.05)),
        "p50": float(s.quantile(0.50)),
        "p95": float(s.quantile(0.95)),
        "max": float(s.max()),
        "n": int(s.shape[0]),
    }


def run_one(ts: datetime, adapter, n, hub_centroids) -> dict:
    """Run OPF for one timestamp and produce a congestion record. Per-step
    failures are caught so a partial record is still returned."""
    try:
        op = adapter.build(ts)
        result = compute_snapshot_batch(n, [ts], {ts: op})[ts]
        if result['status'] == 'infeasible':
            print("  infeasible — retrying with global load scale factor")
            op = adapter.build(ts, force_global_load_sf=True)
            result = compute_snapshot_batch(n, [ts], {ts: op})[ts]
    except Exception as e:
        traceback.print_exc()
        return {"status": "error", "error": f"opf: {e}"}

    if result['status'] != 'ok':
        return {"status": result['status'], "meta": result.get('meta', {})}

    lmps = result['lmps']

    hub_lmps: dict[str, float] = {}
    try:
        hub_lmps = build_hub_lmps(lmps, n, hub_centroids)
    except Exception as e:
        print(f"  build_hub_lmps failed: {e}")

    loads = None
    try:
        loads = build_load_per_bus(n, ts)
    except Exception as e:
        print(f"  build_load_per_bus failed: {e}")

    system_lambda = None
    try:
        system_lambda = float(lmps.dropna().median())
    except Exception as e:
        print(f"  system_lambda proxy failed: {e}")

    cong = compute_congestion(lmps, hub_lmps, loads=loads, system_lambda=system_lambda)
    congestion_diagnostics(cong)

    return {
        "status": "ok",
        "hub_lmps": hub_lmps,
        "system_lambda_proxy": system_lambda,
        "lmp_summary": _stats(lmps),
        "stats": {m: _stats(cong[m]) for m in cong.columns},
        "congestion": {
            m: cong[m].dropna().round(3).to_dict() for m in cong.columns
        },
        "load_scaling_mode": op['meta'].get('load_scaling_mode'),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-id', default='baseline',
                    help="Identifier for this experiment (e.g., 'baseline').")
    args = ap.parse_args()

    results_file = BASE_DIR / f"congestion_results_{args.run_id}.json"

    with open(REF_FILE, 'r') as f:
        refs = json.load(f)

    hub_centroids = pd.read_csv(HUB_CENTROIDS_CSV).set_index('settlement_point')

    mc = pd.read_csv(MARGINAL_COSTS_CSV, index_col=0)
    bus_weather_zones = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    gen_enriched = pd.read_csv(GENERATOR_MATCHES_ENRICHED_CSV)
    n = pypsa.Network(NETWORK_NC)
    n.generators['marginal_cost'] = (
        n.generators.index.map(mc['marginal_cost']).fillna(0)
    )
    conn = psycopg.connect(PG_DSN)
    adapter = OperatingDataAdapter(conn, gen_enriched, bus_weather_zones, n)
    apply_static_mutations(
        n, line_derate=adapter.line_derate, tx_derate=adapter.tx_derate,
    )

    results = []
    for regime, timestamps in refs.items():
        for _ts in timestamps:
            ts = datetime.fromisoformat(_ts).replace(tzinfo=timezone.utc)
            print(f"\n{'=' * 60}\n{regime} | {ts.isoformat()}\n{'=' * 60}")
            try:
                record = run_one(ts, adapter, n, hub_centroids)
            except Exception as e:
                traceback.print_exc()
                record = {"status": "error", "error": str(e)}
            results.append({
                "regime": regime,
                "run_id": args.run_id,
                "ts": _ts,
                **record,
            })

    with open(results_file, 'w') as f:
        json.dump(results, f)
    print(f"\nWrote {len(results)} records -> {results_file}")


if __name__ == '__main__':
    main()
