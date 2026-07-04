"""
ERCOT-side congestion snapshot (sibling to congestion_snapshot.py).

Builds a per-record congestion matrix from REAL ERCOT DAM prices using the
same six reference methods as the model-side 0011 runner. Restricted to the
~1,100 settlement points we have geocoded (the "ERCOT network"):
  - settlement_points_geocoded.csv  (nodal SPs with lat/lon + nameplate)
  - hubs_lz_centroids.csv           (HB_* hubs + LZ_* load zones)

For each reference timestamp:
  1. Pull DAM SPP per tracked SP from ercot_dam_spp.
  2. Pull real system_lambda from dam_system_lambda.
  3. Pull 8 weather-zone loads from load_by_zone.
  4. Build per-SP load weights: each SP gets its weather zone's load divided
     evenly across the SPs in that zone (zone-load-weighted mean of zone-mean
     prices — mirrors the spirit of the model's load_weighted scaling).
  5. Build per-SP nameplate weights from matched_capacity_mw (0 for hubs,
     LZs, and any unmapped nodal).
  6. Reuse compute_congestion() with these inputs (same function as 0011).
  7. Persist to JSON keyed by (regime, ts).

Output per-record schema mirrors 0011 where applicable; ERCOT-specific
fields are documented inline. Phase 4 will design the joined view.

Usage:
    docker compose run --rm compute python -m compute.congestion.ercot_runner
    docker compose run --rm compute python -m compute.congestion.ercot_runner \
        --run-id ercot-baseline \
        --dates-file /compute/sample_specs/reference_dates.json
"""
import gzip
import json
import argparse
import traceback
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import psycopg

from compute.config import PG_DSN
from compute.ercot.transforms import (
    load_tracked_sps,
    assign_weather_zones,
    fetch_dam_spp_batch,
    fetch_system_lambda_batch,
    fetch_zone_loads_batch,
    post_process_one,
)

BASE_DIR = Path(__file__).parent
RUNS_ROOT = BASE_DIR.parent / "runs"
DEFAULT_DATES_FILE = Path("/compute/sample_specs/reference_dates.json")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _load_dates(dates_file: Path) -> dict[str, list[str]]:
    """Accept either flat list of ISO ts or dict {regime: [iso]}."""
    with open(dates_file, 'r') as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return {"all": list(raw)}
    if isinstance(raw, dict):
        return {regime: list(ts_list) for regime, ts_list in raw.items()}
    raise ValueError(
        f"{dates_file}: expected list[str] or dict[str, list[str]], "
        f"got {type(raw).__name__}"
    )


def compute_records(
    timestamps_by_regime: dict[str, list[str]],
    run_id: str = 'inproc',
    chunk_size: int = 24,
    conn=None,
) -> dict:
    """Build per-(regime, ts) ERCOT congestion records in-process.

    Returns
    -------
    dict with keys:
      - records: list[dict] one per (regime, ts) in input order
      - sp_to_zone: pd.Series (SP → weather zone)
      - sp_weights: pd.Series uniform 1.0 per SP — used as bus_weight in
        congestion.aggregate_to_zones. Per-SP load weights from the snapshot
        are zone_load/n_in_zone (constant within zone), so within-zone
        weighted-mean reduces to a simple mean across SPs.
      - tracked: pd.DataFrame indexed by SP (lat, lon, nameplate_mw)
    """
    tracked = load_tracked_sps()
    sp_to_zone = assign_weather_zones(tracked)
    sps_per_zone = sp_to_zone.value_counts().to_dict()
    nameplate = tracked['nameplate_mw'].astype(float)

    print(f"tracked SPs: {len(tracked)}; SPs/zone: {sps_per_zone}")
    print(f"SPs with nameplate>0: {int((nameplate > 0).sum())}")

    flat: list[tuple[str, datetime, str]] = []
    for regime, ts_list in timestamps_by_regime.items():
        for _ts in ts_list:
            ts = datetime.fromisoformat(_ts).replace(tzinfo=timezone.utc)
            flat.append((regime, ts, _ts))

    unique_ts = list(dict.fromkeys(ts for _, ts, _ in flat))
    sps = list(tracked.index)

    owns_conn = conn is None
    if owns_conn:
        conn = psycopg.connect(PG_DSN)
    record_by_ts: dict[datetime, dict] = {}
    try:
        for i in range(0, len(unique_ts), chunk_size):
            chunk = unique_ts[i:i + chunk_size]
            print(
                f"\n{'=' * 60}\n"
                f"chunk {i // chunk_size + 1}: "
                f"{chunk[0].isoformat()} .. {chunk[-1].isoformat()} ({len(chunk)} ts)\n"
                f"{'=' * 60}"
            )
            try:
                spp_by_ts = fetch_dam_spp_batch(conn, chunk, sps)
                lambda_by_ts = fetch_system_lambda_batch(conn, chunk)
                loads_by_ts = fetch_zone_loads_batch(conn, chunk)
            except Exception as e:
                traceback.print_exc()
                for ts in chunk:
                    record_by_ts[ts] = {"status": "error", "error": f"batch fetch: {e}"}
                continue

            for ts in chunk:
                lmps = spp_by_ts.get(ts)
                if lmps is None or lmps.empty:
                    record_by_ts[ts] = {
                        "status": "missing",
                        "reason": "no dam_spp rows for ts",
                    }
                    print(f"  {ts.isoformat()}: missing")
                    continue
                try:
                    record_by_ts[ts] = post_process_one(
                        lmps=lmps,
                        system_lambda=lambda_by_ts.get(ts),
                        zone_loads=loads_by_ts.get(ts, {}),
                        sp_to_zone=sp_to_zone,
                        sps_per_zone=sps_per_zone,
                        nameplate=nameplate,
                    )
                    print(f"  {ts.isoformat()}: ok")
                except Exception as e:
                    traceback.print_exc()
                    record_by_ts[ts] = {"status": "error", "error": str(e)}
    finally:
        if owns_conn:
            conn.close()

    records = []
    for regime, ts, raw_ts in flat:
        rec = record_by_ts.get(ts, {"status": "missing"})
        records.append({
            "regime": regime,
            "run_id": run_id,
            "ts": raw_ts,
            **rec,
        })

    sp_weights = pd.Series(1.0, index=tracked.index)
    return {
        "records": records,
        "sp_to_zone": sp_to_zone,
        "sp_weights": sp_weights,
        "tracked": tracked,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-id', default='baseline',
                    help="Identifier for this experiment.")
    ap.add_argument('--dates-file', type=Path, default=DEFAULT_DATES_FILE,
                    help=f'JSON file: flat list of ISO ts OR dict {{regime: [iso]}}. '
                         f'Default: {DEFAULT_DATES_FILE}.')
    ap.add_argument('--chunk-size', type=int, default=24,
                    help='Timestamps per batched DB round-trip (default 24).')
    ap.add_argument('--output', type=Path, default=None,
                    help='Explicit output path for per-record JSON. When unset, '
                         'derives from --run-id and --records-output.')
    ap.add_argument('--records-output', choices=('gz', 'json'), default='gz',
                    help='Per-record output format when deriving default path '
                         '(default: gz -> .json.gz).')
    args = ap.parse_args()

    if args.output is not None:
        results_file = args.output
    else:
        ext = '.json.gz' if args.records_output == 'gz' else '.json'
        results_file = RUNS_ROOT / args.run_id / "congestion" / f"ercot_results{ext}"
    refs = _load_dates(args.dates_file)

    out = compute_records(
        timestamps_by_regime=refs,
        run_id=args.run_id,
        chunk_size=args.chunk_size,
    )
    records = out['records']

    results_file.parent.mkdir(parents=True, exist_ok=True)
    opener = gzip.open if results_file.suffix == '.gz' else open
    with opener(results_file, 'wt') as f:
        json.dump(records, f)
    print(f"\nWrote {len(records)} records -> {results_file}")

    n_ok = sum(1 for r in records if r.get('status') == 'ok')
    n_missing = sum(1 for r in records if r.get('status') == 'missing')
    n_error = sum(1 for r in records if r.get('status') == 'error')
    n_extreme = sum(
        (r.get('sanity') or {}).get('n_extreme', 0)
        for r in records if r.get('status') == 'ok'
    )
    print(
        f"\nSummary: n_records={len(records)} n_ok={n_ok} "
        f"n_missing={n_missing} n_error={n_error} n_extreme_buses={n_extreme}"
    )


if __name__ == '__main__':
    main()
