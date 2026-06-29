"""
Phase 2 congestion snapshot.

All reference timestamps are split into chunks of --chunk-size (default 6),
each chunk batched through compute_snapshot_batch in one HiGHS call. Per-ts
post-processing (hub LMPs, load-weighted ref, congestion) happens while
that chunk's loads_t.p_set is still resident on the network.

For each reference timestamp:
  1. Pull OPF result from the batched solve
  2. Build inputs to compute_congestion from the model output:
       - hub_lmps: HB_BUSAVG, HB_HOUSTON, HB_NORTH, HB_SOUTH, HB_WEST →
         LMP at synthetic bus nearest each ERCOT hub centroid
         (hubs_lz_centroids.csv).
       - loads:        per-bus load (for load_weighted ref).
       - dispatch:     per-bus dispatched generation (for gen_weighted ref).
       - system_lambda: median bus LMP — model-side proxy for the
         energy-component price (ERCOT publishes NP6-322-CD for the real side).
  3. Compute bus-level congestion under each reference method.
  4. Persist per-record results to JSON keyed by (regime, ts).

Usage:
    docker compose run --rm compute python \
        /compute/experiments/congestion_calculation/congestion_snapshot.py
    docker compose run --rm compute python \
        /compute/experiments/congestion_calculation/congestion_snapshot.py \
        --run-id baseline --dates-file /compute/profiling/reference_dates.json
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
DEFAULT_DATES_FILE = Path("/compute/profiling/reference_dates.json")
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


def build_dispatch_per_bus(dispatch: pd.Series, n: pypsa.Network) -> pd.Series:
    """Aggregate per-generator dispatch (from snapshot result, shed already
    excluded) to per-bus totals."""
    return (
        dispatch.groupby(n.generators.loc[dispatch.index, 'bus']).sum()
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


def _sanity(cong: pd.DataFrame, extreme_threshold: float = 2000.0) -> dict:
    """Lightweight per-record signal: centering check + tail flags. Replaces
    the per-record `stats` block, which carried no method-specific signal."""
    if cong.empty:
        return {
            "simple_mean_centered": False,
            "abs_max": 0.0,
            "n_extreme": 0,
        }
    sm = cong.get("simple_mean")
    centered = (
        sm is not None
        and not sm.dropna().empty
        and abs(float(sm.mean())) < 1e-6
    )
    return {
        "simple_mean_centered": bool(centered),
        "abs_max": float(cong.abs().max().max()),
        "n_extreme": int((cong.abs() > extreme_threshold).sum().sum()),
    }


def post_process_one(result, op, n, hub_centroids, ts) -> dict:
    """Convert a solved per-ts result into a congestion record. Per-step
    failures are caught so a partial record is still returned."""
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

    dispatch_per_bus = None
    try:
        dispatch_per_bus = build_dispatch_per_bus(result['dispatch'], n)
    except Exception as e:
        print(f"  build_dispatch_per_bus failed: {e}")

    system_lambda = None
    try:
        system_lambda = float(lmps.dropna().median())
    except Exception as e:
        print(f"  system_lambda failed: {e}")

    cong = compute_congestion(
        lmps, hub_lmps,
        loads=loads, dispatch=dispatch_per_bus, system_lambda=system_lambda,
    )
    congestion_diagnostics(cong)

    bus_loads: dict[str, float] = {}
    if loads is not None:
        # Drop zero-load buses to keep JSON compact; consumers treat
        # missing as 0.
        nz = loads[loads != 0.0].round(3)
        bus_loads = {str(b): float(v) for b, v in nz.items()}

    return {
        "status": "ok",
        "hub_lmps": hub_lmps,
        "system_lambda": system_lambda,
        "lmp_summary": _stats(lmps),
        "sanity": _sanity(cong),
        "congestion": {
            m: cong[m].dropna().round(3).to_dict() for m in cong.columns
        },
        "bus_loads": bus_loads,
        "load_scaling_mode": op['meta'].get('load_scaling_mode'),
    }


def _load_dates(dates_file: Path) -> dict[str, list[str]]:
    """Read a dates file in either schema:
      - dict[regime, list[iso_ts]]  (e.g. reference_dates.json)
      - flat list[iso_ts]           (regime defaults to 'all')
    """
    with open(dates_file, 'r') as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return {"all": list(raw)}
    if isinstance(raw, dict):
        return {regime: list(ts_list) for regime, ts_list in raw.items()}
    raise ValueError(
        f"{dates_file}: expected list[str] or dict[str, list[str]], got {type(raw).__name__}"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-id', default='baseline',
                    help="Identifier for this experiment (e.g., 'baseline').")
    ap.add_argument('--chunk-size', type=int, default=6,
                    help='Snapshots per batched solve (default 6).')
    ap.add_argument('--dates-file', type=Path, default=DEFAULT_DATES_FILE,
                    help='JSON file: flat list of ISO timestamps OR dict {regime: [iso]}. '
                         f'Default: {DEFAULT_DATES_FILE}.')
    args = ap.parse_args()

    results_file = BASE_DIR / f"congestion_results_{args.run_id}.json"

    refs = _load_dates(args.dates_file)

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

    # Flatten into (regime, ts) in input order. Multiple regimes are allowed
    # to share a ts; we solve unique ts once and emit one record per
    # (regime, ts) pair.
    flat: list[tuple[str, datetime, str]] = []
    for regime, timestamps in refs.items():
        for _ts in timestamps:
            ts = datetime.fromisoformat(_ts).replace(tzinfo=timezone.utc)
            flat.append((regime, ts, _ts))

    unique_ts: list[datetime] = list(dict.fromkeys(ts for _, ts, _ in flat))

    # Build adapter ops upfront so the chunk solves don't hold an adapter
    # call in the hot loop. Failures are recorded per-ts.
    op_by_ts: dict[datetime, dict] = {}
    op_errors: dict[datetime, str] = {}
    for ts in unique_ts:
        try:
            op_by_ts[ts] = adapter.build(ts)
        except Exception as e:
            traceback.print_exc()
            op_errors[ts] = str(e)

    record_by_ts: dict[datetime, dict] = {
        ts: {"status": "error", "error": f"opf: {err}"}
        for ts, err in op_errors.items()
    }

    solvable = [ts for ts in unique_ts if ts in op_by_ts]
    for i in range(0, len(solvable), args.chunk_size):
        chunk = solvable[i:i + args.chunk_size]
        sub_op = {ts: op_by_ts[ts] for ts in chunk}
        print(
            f"\n{'=' * 60}\n"
            f"chunk {i // args.chunk_size + 1}: "
            f"{chunk[0].isoformat()} .. {chunk[-1].isoformat()} ({len(chunk)} ts)\n"
            f"{'=' * 60}"
        )
        try:
            results = compute_snapshot_batch(n, chunk, sub_op)
        except Exception as e:
            traceback.print_exc()
            for ts in chunk:
                record_by_ts[ts] = {"status": "error", "error": f"opf: {e}"}
            continue

        # Post-process ok results NOW, while n.loads_t.p_set still holds
        # this chunk's loads. Retries below overwrite loads_t.
        for ts in chunk:
            r = results[ts]
            if r['status'] == 'ok':
                record_by_ts[ts] = post_process_one(
                    r, op_by_ts[ts], n, hub_centroids, ts,
                )
            elif r['status'] != 'infeasible':
                record_by_ts[ts] = {"status": r['status'], "meta": r.get('meta', {})}

        # Per-ts retry for infeasible snapshots with global SF.
        for ts in chunk:
            if results[ts]['status'] != 'infeasible':
                continue
            print(f"  {ts.isoformat()}: infeasible — retrying with global SF")
            try:
                op_retry = adapter.build(ts, force_global_load_sf=True)
                retry = compute_snapshot_batch(n, [ts], {ts: op_retry})[ts]
            except Exception as e:
                traceback.print_exc()
                record_by_ts[ts] = {"status": "error", "error": f"opf retry: {e}"}
                continue
            if retry['status'] == 'ok':
                record_by_ts[ts] = post_process_one(
                    retry, op_retry, n, hub_centroids, ts,
                )
            else:
                record_by_ts[ts] = {
                    "status": retry['status'],
                    "meta": retry.get('meta', {}),
                }

    records = []
    for regime, ts, raw_ts in flat:
        rec = record_by_ts.get(ts, {"status": "missing"})
        records.append({
            "regime": regime,
            "run_id": args.run_id,
            "ts": raw_ts,
            **rec,
        })

    with open(results_file, 'w') as f:
        json.dump(records, f)
    print(f"\nWrote {len(records)} records -> {results_file}")

    n_ok = sum(1 for r in records if r.get('status') == 'ok')
    n_missing = len(records) - n_ok
    n_extreme = sum(
        (r.get('sanity') or {}).get('n_extreme', 0)
        for r in records if r.get('status') == 'ok'
    )
    print(
        f"\nSummary: n_records={len(records)} n_ok={n_ok} n_missing={n_missing} "
        f"n_extreme_buses={n_extreme}"
    )


if __name__ == '__main__':
    main()
