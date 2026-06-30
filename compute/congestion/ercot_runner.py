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
import json
import argparse
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

from compute.config import PG_DSN

from .compute import (
    compute_congestion, congestion_diagnostics,
    CUSTOM_HUBS, HUB_BUSAVG,
)

BASE_DIR = Path(__file__).parent
DEFAULT_DATES_FILE = Path("/compute/sample_specs/reference_dates.json")
HUB_CENTROIDS_CSV = Path("/data/processed/hubs_lz_centroids.csv")
SP_GEOCODED_CSV = Path("/data/processed/settlement_points_geocoded.csv")
BUS_WEATHER_LOAD_ZONES_CSV = Path("/data/processed/bus_ercot_weather_load_zones.csv")

# 8 ERCOT weather zones (load_by_zone column names).
WEATHER_ZONES = (
    'coast', 'east', 'far_west', 'north',
    'north_central', 'south_central', 'southern', 'west',
)


# ---------------------------------------------------------------------------
# Setup (once per run)
# ---------------------------------------------------------------------------

def load_tracked_sps() -> pd.DataFrame:
    """Union of geocoded nodal SPs + hub/LZ centroids. Columns:
    settlement_point (index), lat, lon, nameplate_mw."""
    sp = pd.read_csv(SP_GEOCODED_CSV)[
        ['settlement_point', 'lat', 'lon', 'matched_capacity_mw']
    ].rename(columns={'matched_capacity_mw': 'nameplate_mw'})
    hubs = pd.read_csv(HUB_CENTROIDS_CSV)[['settlement_point', 'lat', 'lon']]
    hubs['nameplate_mw'] = 0.0  # hubs/LZs are aggregation points, not generators

    combined = pd.concat([sp, hubs], ignore_index=True)
    combined['nameplate_mw'] = combined['nameplate_mw'].fillna(0.0)
    # Drop dup SPs (a hub could in principle appear in both files); keep first
    combined = combined.drop_duplicates(subset='settlement_point', keep='first')
    return combined.set_index('settlement_point')


def assign_weather_zones(tracked: pd.DataFrame) -> pd.Series:
    """For each tracked SP, nearest-bus lookup -> weather zone (one of
    WEATHER_ZONES). Pattern mirrors congestion_snapshot.build_hub_lmps."""
    bz = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    bz['ercot_weather_zone'] = (
        bz['ercot_weather_zone'].astype(str).str.lower().str.replace(' ', '_')
    )
    valid_bz = bz.dropna(subset=['lat', 'lon', 'ercot_weather_zone'])
    bus_coords = valid_bz[['lat', 'lon']].to_numpy()
    bus_zones = valid_bz['ercot_weather_zone'].to_numpy()

    sp_xy = tracked[['lat', 'lon']].dropna()
    out = pd.Series(index=tracked.index, dtype=object)
    for sp, (slat, slon) in sp_xy.iterrows():
        d2 = (bus_coords[:, 0] - slat) ** 2 + (bus_coords[:, 1] - slon) ** 2
        out.loc[sp] = bus_zones[int(np.argmin(d2))]
    return out


# ---------------------------------------------------------------------------
# Batched DB queries (one round-trip per data source per chunk of timestamps)
# ---------------------------------------------------------------------------

def fetch_dam_spp_batch(
    conn,
    ts_list: list[datetime],
    sps: list[str],
) -> dict[datetime, pd.Series]:
    """SPP per (ts, tracked SP) across a batch of timestamps. DST: take the
    dst_flag=ASC row per (ts, sp) (mirrors operating_data_adapter)."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT ON (interval_ts, settlement_point)
               interval_ts, settlement_point, dam_spp
        FROM ercot_dam_spp
        WHERE interval_ts = ANY(%s) AND settlement_point = ANY(%s)
        ORDER BY interval_ts, settlement_point, dst_flag ASC
        """,
        (ts_list, sps),
    )
    by_ts: dict[datetime, dict[str, float]] = {}
    for ts, sp, v in cur.fetchall():
        by_ts.setdefault(ts, {})[sp] = float(v)
    return {
        ts: pd.Series(d, name='dam_spp') for ts, d in by_ts.items()
    }


def fetch_system_lambda_batch(
    conn,
    ts_list: list[datetime],
) -> dict[datetime, float]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT ON (interval_ts) interval_ts, system_lambda
        FROM dam_system_lambda
        WHERE interval_ts = ANY(%s)
        ORDER BY interval_ts, dst_flag ASC
        """,
        (ts_list,),
    )
    return {ts: float(v) for ts, v in cur.fetchall()}


def fetch_zone_loads_batch(
    conn,
    ts_list: list[datetime],
) -> dict[datetime, dict[str, float]]:
    """load_by_zone is 15-min so several rows can share an hour-ending
    timestamp; aggregate by averaging within the hour."""
    cols = ', '.join(f'AVG({z}) AS {z}' for z in WEATHER_ZONES)
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT interval_ts, {cols}
        FROM load_by_zone
        WHERE interval_ts = ANY(%s)
        GROUP BY interval_ts
        """,
        (ts_list,),
    )
    out: dict[datetime, dict[str, float]] = {}
    for row in cur.fetchall():
        ts = row[0]
        out[ts] = {
            z: (float(v) if v is not None else 0.0)
            for z, v in zip(WEATHER_ZONES, row[1:])
        }
    return out


# ---------------------------------------------------------------------------
# Per-record build
# ---------------------------------------------------------------------------

def build_hub_lmps(lmps: pd.Series) -> dict[str, float]:
    """Read off the hub SPP values from the dam_spp result. Hubs missing
    from this hour's data are simply absent from the dict."""
    out: dict[str, float] = {}
    for hub in (HUB_BUSAVG, *CUSTOM_HUBS):
        if hub in lmps.index and pd.notna(lmps[hub]):
            out[hub] = float(lmps[hub])
    return out


def build_sp_load_weights(
    lmps_index: pd.Index,
    sp_to_zone: pd.Series,
    zone_loads: dict[str, float],
    sps_per_zone: dict[str, int],
) -> pd.Series:
    """Per-SP load weight: zone_load / count(SPs in zone). Indexed to lmps."""
    weights = pd.Series(0.0, index=lmps_index)
    for sp in lmps_index:
        zone = sp_to_zone.get(sp)
        if zone is None or zone not in zone_loads:
            continue
        n = sps_per_zone.get(zone, 0)
        if n <= 0:
            continue
        weights[sp] = zone_loads[zone] / n
    return weights


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


def _sanity(
    cong: pd.DataFrame,
    n_sp: int,
    n_sp_with_nameplate: int,
    hub_lmps: dict,
    extreme_threshold: float = 2000.0,
) -> dict:
    """Mirror of 0011 sanity block + ERCOT coverage flags.

    n_sp_with_nameplate: count of SPs with positive matched_capacity_mw used
    in the gen_weighted reference. SPs without nameplate still receive a
    gen_weighted congestion value (scalar subtraction), they just don't
    contribute their LMP to computing the scalar. Watch this number — if it
    drifts well below n_settlement_points the gen_weighted reference is
    being computed from a thin / potentially biased subset.
    """
    sm = cong.get("simple_mean")
    centered = (
        sm is not None
        and not sm.dropna().empty
        and abs(float(sm.mean())) < 1e-6
    )
    return {
        "simple_mean_centered": bool(centered),
        "abs_max": float(cong.abs().max().max()) if not cong.empty else 0.0,
        "n_extreme": int((cong.abs() > extreme_threshold).sum().sum())
                     if not cong.empty else 0,
        "n_settlement_points": int(n_sp),
        "n_sp_with_nameplate": int(n_sp_with_nameplate),
        "n_missing_hubs": int(
            len({HUB_BUSAVG, *CUSTOM_HUBS}) - len(hub_lmps)
        ),
    }


def post_process_one(
    lmps: pd.Series,
    system_lambda: float | None,
    zone_loads: dict[str, float],
    sp_to_zone: pd.Series,
    sps_per_zone: dict[str, int],
    nameplate: pd.Series,
) -> dict:
    """Build one per-record dict from pre-fetched batch inputs."""
    hub_lmps = build_hub_lmps(lmps)
    sp_load = build_sp_load_weights(
        lmps.index, sp_to_zone, zone_loads, sps_per_zone,
    )
    nameplate_aligned = nameplate.reindex(lmps.index).fillna(0.0)

    cong, refs = compute_congestion(
        lmps, hub_lmps,
        loads=sp_load,
        dispatch=nameplate_aligned,
        system_lambda=system_lambda,
    )
    congestion_diagnostics(cong)

    return {
        "status": "ok",
        "hub_lmps": hub_lmps,
        # Per-method scalar reference prices — see model-side notes.
        # On the ERCOT side `system_lambda` carries the real NP4-523-CD
        # value; `system_lambda_kkt` and `system_lambda_merit_order` are
        # always None (model-only estimators).
        "reference_prices": refs,
        "lmp_summary": _stats(lmps),
        "sanity": _sanity(
            cong,
            n_sp=len(lmps),
            n_sp_with_nameplate=int((nameplate_aligned > 0).sum()),
            hub_lmps=hub_lmps,
        ),
        "congestion": {
            m: cong[m].dropna().round(3).to_dict() for m in cong.columns
        },
        "data_source": "dam",
    }


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
    args = ap.parse_args()

    results_file = BASE_DIR / f"ercot_congestion_results_{args.run_id}.json"
    refs = _load_dates(args.dates_file)

    out = compute_records(
        timestamps_by_regime=refs,
        run_id=args.run_id,
        chunk_size=args.chunk_size,
    )
    records = out['records']

    with open(results_file, 'w') as f:
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
