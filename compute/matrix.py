"""Build congestion_matrices.npz from bus_snapshots + snapshot_meta and the
ERCOT tables.

Streams per-(method, bus, hour) model congestion from ``bus_snapshots.lmp``
and ``snapshot_meta.reference_prices``; the ERCOT side is still built via
``ercot_runner.compute_records`` for now (Commit 3 replaces it with direct
DB streaming through ``compute.ercot.transforms``).

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
from compute.congestion.compute import METHODS
from compute.congestion import ercot_runner as ercot_snap
from compute.run_pipeline import _ingest_hint, _load_dates

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
RUNS_ROOT = BASE_DIR / "runs"


# ---------------------------------------------------------------------------
# Model side: stream from bus_snapshots + snapshot_meta
# ---------------------------------------------------------------------------

def _preflight(conn, timestamps: list[datetime]) -> list[datetime]:
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
# ERCOT side (still record-based; Commit 3 replaces with DB streaming)
# ---------------------------------------------------------------------------

def build_ercot_matrices(
    ercot_recs: list[dict],
    timestamps: list[datetime],
    ref_methods: list[str],
) -> tuple[dict[str, np.ndarray], list[str]]:
    """Convert ercot_runner records into per-method ercot_C matrices aligned
    to ``timestamps``."""
    ts_key = {ts.isoformat(): j for j, ts in enumerate(timestamps)}
    sp_set: set[str] = set()
    for r in ercot_recs:
        if r.get('status') != 'ok':
            continue
        for method_dict in (r.get('congestion') or {}).values():
            sp_set.update(method_dict.keys())
    sp_ids = sorted(sp_set)
    sp_idx = {s: i for i, s in enumerate(sp_ids)}

    n_sp = len(sp_ids)
    n_hours = len(timestamps)
    ercot_C: dict[str, np.ndarray] = {
        m: np.full((n_sp, n_hours), np.nan, dtype=float) for m in ref_methods
    }
    for r in ercot_recs:
        if r.get('status') != 'ok':
            continue
        ts_str = r.get('ts')
        if ts_str is None:
            continue
        j = ts_key.get(ts_str)
        if j is None:
            continue
        cong = r.get('congestion') or {}
        for m in ref_methods:
            per_sp = cong.get(m)
            if not per_sp:
                continue
            for sp, v in per_sp.items():
                i = sp_idx.get(sp)
                if i is None or v is None:
                    continue
                ercot_C[m][i, j] = float(v)
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
        missing = _preflight(conn, timestamps)
        if missing:
            print(
                f"\n{len(missing)} timestamp(s) missing or not status='ok' "
                f"in snapshot_meta:",
                file=sys.stderr,
            )
            for ts in missing[:10]:
                print(f"  {ts.isoformat()}", file=sys.stderr)
            if len(missing) > 10:
                print(f"  ... and {len(missing) - 10} more", file=sys.stderr)
            print(f"\n  {_ingest_hint(missing)}", file=sys.stderr)
            sys.exit(1)
        print(f"pre-flight: {len(timestamps)} ts all status='ok'")

        print(f"streaming bus_snapshots for {len(timestamps)} ts × "
              f"{len(args.ref_methods)} methods...")
        model_C, bus_ids = build_model_matrices(
            conn, timestamps, args.ref_methods,
        )
        print(f"  model: {len(bus_ids)} buses × {len(timestamps)} hours")

    # ERCOT side: still via ercot_runner records (Commit 3 replaces this).
    print("computing ERCOT side via ercot_runner.compute_records...")
    ercot_out = ercot_snap.compute_records(
        timestamps_by_regime={'all': [ts.isoformat() for ts in timestamps]},
        run_id=args.run_id,
    )
    ercot_C, sp_ids = build_ercot_matrices(
        ercot_out['records'], timestamps, args.ref_methods,
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
