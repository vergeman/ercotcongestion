"""Build congestion_matrices.npz from bus_snapshots + snapshot_meta and the
ERCOT tables.

Streams per-(method, bus, hour) model congestion from ``bus_snapshots.lmp``
and ``snapshot_meta.reference_prices``; the ERCOT side streams
``ercot_dam_spp`` + ``dam_system_lambda`` + ``load_by_zone`` through the
per-timestamp transforms in ``compute.ercot.transforms``.

Usage:
    docker compose run --rm compute python -m compute.matrix \\
        --run-id <id> --dates-file /compute/sample_specs/<file>.json
"""
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import psycopg

from compute.config import PG_DSN
from compute.congestion.compute import METHODS, compute_congestion
from compute.ercot.transforms import (
    assign_weather_zones,
    build_hub_lmps,
    build_sp_load_weights,
    fetch_dam_spp_batch,
    fetch_system_lambda_batch,
    fetch_zone_loads_batch,
    load_tracked_sps,
)
from compute.run_pipeline import _load_dates

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
RUNS_ROOT = BASE_DIR / "runs"

ERCOT_CHUNK_SIZE = 168  # 1 week of hourly ts per DB round-trip


# ---------------------------------------------------------------------------
# Model side: stream from bus_snapshots + snapshot_meta
# ---------------------------------------------------------------------------

def _preflight_model(conn, timestamps: list[datetime]) -> list[datetime]:
    """Return timestamps missing or with status != 'ok' in snapshot_meta."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT interval_ts, status FROM snapshot_meta "
            "WHERE interval_ts = ANY(%s)",
            (timestamps,),
        )
        status_by_ts = {ts: status for ts, status in cur.fetchall()}
    return [ts for ts in timestamps if status_by_ts.get(ts) != 'ok']


def _fetch_reference_prices(
    conn, timestamps: list[datetime],
) -> dict[datetime, dict]:
    """Fetch snapshot_meta.reference_prices per ts."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT interval_ts, reference_prices FROM snapshot_meta "
            "WHERE interval_ts = ANY(%s)",
            (timestamps,),
        )
        return {ts: (refs or {}) for ts, refs in cur.fetchall()}


def _fetch_bus_ids(conn, timestamps: list[datetime]) -> list[str]:
    """Discover all distinct bus_ids present in bus_snapshots for the ts list."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT bus_id FROM bus_snapshots "
            "WHERE interval_ts = ANY(%s) "
            "ORDER BY bus_id",
            (timestamps,),
        )
        return [row[0] for row in cur.fetchall()]


def _build_ref_vec(
    refs_by_ts: dict[datetime, dict],
    timestamps: list[datetime],
    ref_methods: list[str],
) -> dict[str, np.ndarray]:
    """Per-method scalar reference-price vector aligned to timestamps."""
    n_hours = len(timestamps)
    ts_idx = {ts: j for j, ts in enumerate(timestamps)}
    out: dict[str, np.ndarray] = {}
    for m in ref_methods:
        v = np.full(n_hours, np.nan, dtype=float)
        for ts, refs in refs_by_ts.items():
            r = refs.get(m)
            if r is None:
                continue
            v[ts_idx[ts]] = float(r)
        out[m] = v
    return out


def build_model_matrices(
    conn,
    timestamps: list[datetime],
    ref_methods: list[str],
) -> tuple[dict[str, np.ndarray], list[str]]:
    """Stream bus_snapshots + snapshot_meta and fill per-method model_C.

    Congestion for each method is ``lmp[bus, ts] - reference_prices[method][ts]``.
    Any (bus, ts) whose lmp is NULL, or whose method reference is NULL, stays
    NaN in the output.
    """
    refs_by_ts = _fetch_reference_prices(conn, timestamps)
    bus_ids = _fetch_bus_ids(conn, timestamps)
    n_bus = len(bus_ids)
    n_hours = len(timestamps)

    bus_idx = {b: i for i, b in enumerate(bus_ids)}
    ts_idx = {t: j for j, t in enumerate(timestamps)}
    ref_vec = _build_ref_vec(refs_by_ts, timestamps, ref_methods)

    model_C: dict[str, np.ndarray] = {
        m: np.full((n_bus, n_hours), np.nan, dtype=float) for m in ref_methods
    }

    with conn.cursor(name='bus_snapshots_stream') as cur:
        cur.itersize = 10_000
        cur.execute(
            "SELECT interval_ts, bus_id, lmp FROM bus_snapshots "
            "WHERE interval_ts = ANY(%s) AND lmp IS NOT NULL",
            (timestamps,),
        )
        for ts, bus_id, lmp in cur:
            i = bus_idx.get(bus_id)
            if i is None:
                continue
            j = ts_idx.get(ts)
            if j is None:
                continue
            lmp_f = float(lmp)
            for m in ref_methods:
                r = ref_vec[m][j]
                if not np.isnan(r):
                    model_C[m][i, j] = lmp_f - r

    return model_C, bus_ids


# ---------------------------------------------------------------------------
# ERCOT side: stream from ercot_dam_spp + dam_system_lambda + load_by_zone
# ---------------------------------------------------------------------------

def _preflight_ercot(conn, timestamps: list[datetime]) -> list[datetime]:
    """Return timestamps with no rows in ercot_dam_spp."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT interval_ts FROM ercot_dam_spp "
            "WHERE interval_ts = ANY(%s)",
            (timestamps,),
        )
        present = {row[0] for row in cur.fetchall()}
    return [ts for ts in timestamps if ts not in present]


def _model_ingest_hint(missing: list[datetime]) -> str:
    """Suggested write_snapshots.py invocation covering [min, max] of missing ts."""
    lo = min(missing).strftime("%Y-%m-%dT%H")
    hi = max(missing).strftime("%Y-%m-%dT%H")
    return (
        "docker compose run --rm compute python /compute/write_snapshots.py "
        f"--start {lo} --end {hi}"
    )


def _ercot_ingest_hint(missing: list[datetime]) -> str:
    lo = min(missing).strftime("%Y-%m-%d")
    hi = max(missing).strftime("%Y-%m-%d")
    return (
        "docker compose run --rm app python /data/ercot/backfill.py "
        f"--start {lo} --end {hi} --endpoint dam_spp"
    )


def build_ercot_matrices(
    conn,
    timestamps: list[datetime],
    ref_methods: list[str],
    chunk_size: int = ERCOT_CHUNK_SIZE,
) -> tuple[dict[str, np.ndarray], list[str]]:
    """Stream ERCOT DAM SPP / λ / zone-loads and fill per-method ercot_C.

    Per-ts flow mirrors ``ercot.transforms.post_process_one`` but writes
    directly into pre-allocated ``(n_sp, n_hours)`` matrices instead of
    building record dicts.
    """
    tracked = load_tracked_sps()
    sp_to_zone = assign_weather_zones(tracked)
    sps_per_zone = sp_to_zone.value_counts().to_dict()
    nameplate = tracked['nameplate_mw'].astype(float)

    sp_ids = list(tracked.index)
    sp_idx = {s: i for i, s in enumerate(sp_ids)}
    ts_idx = {t: j for j, t in enumerate(timestamps)}
    n_sp = len(sp_ids)
    n_hours = len(timestamps)

    ercot_C: dict[str, np.ndarray] = {
        m: np.full((n_sp, n_hours), np.nan, dtype=float) for m in ref_methods
    }

    for start in range(0, n_hours, chunk_size):
        chunk = timestamps[start:start + chunk_size]
        spp_by_ts = fetch_dam_spp_batch(conn, chunk, sp_ids)
        lambda_by_ts = fetch_system_lambda_batch(conn, chunk)
        loads_by_ts = fetch_zone_loads_batch(conn, chunk)

        for ts in chunk:
            lmps = spp_by_ts.get(ts)
            if lmps is None or lmps.empty:
                continue
            hub_lmps = build_hub_lmps(lmps)
            sp_load = build_sp_load_weights(
                lmps.index, sp_to_zone, loads_by_ts.get(ts, {}), sps_per_zone,
            )
            nameplate_aligned = nameplate.reindex(lmps.index).fillna(0.0)
            cong, _ = compute_congestion(
                lmps, hub_lmps,
                loads=sp_load,
                dispatch=nameplate_aligned,
                system_lambda=lambda_by_ts.get(ts),
            )

            j = ts_idx[ts]
            for m in ref_methods:
                if m not in cong.columns:
                    continue
                col = cong[m]
                sp_positions = np.array(
                    [sp_idx.get(sp, -1) for sp in col.index], dtype=int,
                )
                keep = sp_positions >= 0
                if not keep.any():
                    continue
                vals = col.to_numpy(dtype=float)
                ercot_C[m][sp_positions[keep], j] = vals[keep]

    return ercot_C, sp_ids


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def write_matrices_npz(
    path: Path,
    model_C: dict[str, np.ndarray],
    ercot_C: dict[str, np.ndarray],
    bus_ids: list[str],
    sp_ids: list[str],
    timestamps: list[datetime],
    ref_methods: list[str],
) -> None:
    hours = np.array([ts.isoformat() for ts in timestamps], dtype=str)
    bus_arr = np.array(bus_ids, dtype=str)
    sp_arr = np.array(sp_ids, dtype=str)
    arrays: dict[str, np.ndarray] = {}
    for m in ref_methods:
        arrays[f"{m}_model_C"] = model_C[m]
        arrays[f"{m}_ercot_C"] = ercot_C[m]
        arrays[f"{m}_model_bus_ids"] = bus_arr
        arrays[f"{m}_ercot_sp_ids"] = sp_arr
        arrays[f"{m}_model_hours"] = hours
        arrays[f"{m}_ercot_hours"] = hours
    np.savez_compressed(path, **arrays)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _emit_preflight_error(
    missing: list[datetime], label: str, hint: str,
) -> None:
    print(
        f"\n{len(missing)} timestamp(s) {label}:",
        file=sys.stderr,
    )
    for ts in missing[:10]:
        print(f"  {ts.isoformat()}", file=sys.stderr)
    if len(missing) > 10:
        print(f"  ... and {len(missing) - 10} more", file=sys.stderr)
    print(f"\n  {hint}", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-id', required=True,
                    help='Run identifier. Outputs go to '
                         'compute/runs/<run_id>/matrix/.')
    ap.add_argument('--dates-file', type=Path, required=True,
                    help='JSON file: flat list of ISO ts OR dict {regime: [iso]}.')
    ap.add_argument('--ref-methods', nargs='+', default=list(METHODS),
                    choices=list(METHODS),
                    help='Subset of reference methods (default: all).')
    args = ap.parse_args()

    timestamps = _load_dates(args.dates_file)
    if not timestamps:
        raise SystemExit(f"no timestamps in {args.dates_file}")

    out_dir = RUNS_ROOT / args.run_id / "matrix"
    out_dir.mkdir(parents=True, exist_ok=True)
    npz_path = out_dir / "congestion_matrices.npz"

    with psycopg.connect(PG_DSN) as conn:
        missing_model = _preflight_model(conn, timestamps)
        if missing_model:
            _emit_preflight_error(
                missing_model,
                "missing or not status='ok' in snapshot_meta",
                _model_ingest_hint(missing_model),
            )
            sys.exit(1)

        missing_ercot = _preflight_ercot(conn, timestamps)
        if missing_ercot:
            _emit_preflight_error(
                missing_ercot,
                "absent from ercot_dam_spp",
                _ercot_ingest_hint(missing_ercot),
            )
            sys.exit(1)

        print(f"pre-flight: {len(timestamps)} ts ok in snapshot_meta and "
              f"ercot_dam_spp")

        print(f"streaming bus_snapshots for {len(timestamps)} ts × "
              f"{len(args.ref_methods)} methods...")
        model_C, bus_ids = build_model_matrices(
            conn, timestamps, args.ref_methods,
        )
        print(f"  model: {len(bus_ids)} buses × {len(timestamps)} hours")

        print(f"streaming ERCOT DAM SPP / λ / zone-loads for "
              f"{len(timestamps)} ts...")
        ercot_C, sp_ids = build_ercot_matrices(
            conn, timestamps, args.ref_methods,
        )
        print(f"  ercot: {len(sp_ids)} SPs × {len(timestamps)} hours")

    write_matrices_npz(
        npz_path, model_C, ercot_C, bus_ids, sp_ids, timestamps, args.ref_methods,
    )
    print(
        f"wrote {npz_path} "
        f"(n_refs={len(args.ref_methods)}, "
        f"bytes={npz_path.stat().st_size})"
    )


if __name__ == '__main__':
    main()
