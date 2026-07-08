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


def _fetch_bus_ids(
    conn, timestamps: list[datetime],
) -> tuple[list[str], list[str]]:
    """Return (kept, dropped) bus_ids for the ts window.

    A bus is *kept* only if it has a non-NULL LMP at every ts. Isolated /
    orphan buses (typically a few dozen in this network) don't get a
    marginal price from the OPF and would inject NaN rows into model_C;
    downstream SVD / correlation math can't handle those, so we filter
    at the matrix boundary rather than special-case NaN everywhere.
    """
    n_ts = len(timestamps)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT bus_id, COUNT(lmp) AS n_lmp "
            "FROM bus_snapshots "
            "WHERE interval_ts = ANY(%s) "
            "GROUP BY bus_id "
            "ORDER BY bus_id",
            (timestamps,),
        )
        rows = cur.fetchall()
    kept = [bus for bus, n_lmp in rows if n_lmp == n_ts]
    dropped = [bus for bus, n_lmp in rows if n_lmp != n_ts]
    return kept, dropped


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
    Any (bus, ts) whose method reference is NULL stays NaN. Buses whose LMP
    is NULL at any ts are excluded up front by ``_fetch_bus_ids`` to keep
    model_C free of LMP-driven NaN rows.
    """
    refs_by_ts = _fetch_reference_prices(conn, timestamps)
    bus_ids, dropped_bus_ids = _fetch_bus_ids(conn, timestamps)
    if dropped_bus_ids:
        preview = ", ".join(dropped_bus_ids[:10])
        more = "" if len(dropped_bus_ids) <= 10 else f" ... (+{len(dropped_bus_ids) - 10} more)"
        print(
            f"  dropped {len(dropped_bus_ids)} bus(es) with NULL lmp at 1+ ts: "
            f"{preview}{more}"
        )
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

    # Drop SPs that NEVER appeared in DAM SPP over the entire window —
    # chronically missing points that would just create all-NaN rows.
    # Partial-coverage SPs (data on most hours, missing a few) are kept;
    # their missing hours are pruned globally by _prune_structural_hours
    # so we don't blacklist a settlement point over one bad day.
    if ref_methods:
        any_finite = np.zeros(n_sp, dtype=bool)
        for m in ref_methods:
            any_finite |= np.isfinite(ercot_C[m]).any(axis=1)
        if not any_finite.all():
            dropped_sp_ids = [sp_ids[i] for i in range(n_sp) if not any_finite[i]]
            for m in ref_methods:
                ercot_C[m] = ercot_C[m][any_finite]
            sp_ids = [sp for sp, k in zip(sp_ids, any_finite) if k]
            preview = ", ".join(dropped_sp_ids[:10])
            more = "" if len(dropped_sp_ids) <= 10 else f" ... (+{len(dropped_sp_ids) - 10} more)"
            print(
                f"  dropped {len(dropped_sp_ids)} SP(s) with no DAM SPP "
                f"coverage anywhere in window: {preview}{more}"
            )

    return ercot_C, sp_ids


SP_COVERAGE_STRATEGIES = ("max_area", "max_hours", "threshold")


def _structural_missing(
    mats: dict[str, np.ndarray], ref_methods: list[str],
) -> np.ndarray:
    """(row, hour) NaN in every method — LMP/SPP absent, not a method gap."""
    first = ref_methods[0]
    missing = np.isnan(mats[first])
    for m in ref_methods[1:]:
        missing &= np.isnan(mats[m])
    return missing


def _first_dense_hour(missing: np.ndarray) -> np.ndarray:
    """Per-row earliest hour index from which the row is fully dense to the end.

    Equals ``1 + (last structural-NaN column index)`` if any NaN exists,
    else 0. Non-monotonic gaps are handled conservatively — a row with a
    late-window gap can never be part of a rectangle that starts before
    that gap.
    """
    n_rows, n_cols = missing.shape
    if n_rows == 0:
        return np.zeros(0, dtype=int)
    col_idx = np.arange(n_cols)
    # For each row: max col index where missing is True, or -1 if none.
    masked = np.where(missing, col_idx, -1)
    last_nan = masked.max(axis=1)
    return (last_nan + 1).astype(int)


def _log_sweep(
    sorted_first_dense: np.ndarray,
    hours_kept: np.ndarray,
    areas: np.ndarray,
    k_sel: int,
    timestamps: list[datetime],
    dropped_sp_ids: list[str],
    strategy: str,
    min_sp_fraction: float,
) -> None:
    """Emit the sweep table so the chosen cutoff is auditable."""
    n_sp = len(sorted_first_dense)
    print(
        f"  dense-rectangle sweep (strategy={strategy}, "
        f"min_sp_fraction={min_sp_fraction:.2f}):"
    )
    print("    k    n_sp_kept  n_hours_kept       area  latest_kept_sp_first_seen")

    def _row(k: int, marker: str = " ") -> None:
        idx = k - 1
        cutoff = int(sorted_first_dense[idx])
        ts_str = timestamps[cutoff].isoformat() if 0 <= cutoff < len(timestamps) else "-"
        print(
            f"  {marker} {k:>4}  {k:>9}  {int(hours_kept[idx]):>12}  "
            f"{int(areas[idx]):>9}  {ts_str}"
        )

    # Chosen k, then the 3 next-best alternatives by area (excluding chosen).
    _row(k_sel, marker="*")
    order = np.argsort(-areas)
    alt_shown = 0
    for pos in order:
        k = int(pos) + 1
        if k == k_sel:
            continue
        _row(k)
        alt_shown += 1
        if alt_shown >= 3:
            break

    if dropped_sp_ids:
        preview = ", ".join(dropped_sp_ids[:10])
        more = (
            "" if len(dropped_sp_ids) <= 10
            else f" ... (+{len(dropped_sp_ids) - 10} more)"
        )
        print(
            f"  dropped {len(dropped_sp_ids)} SP(s) to enlarge hour window "
            f"({100.0 * len(dropped_sp_ids) / n_sp:.1f}% of SPs): "
            f"{preview}{more}"
        )


def _select_dense_rectangle(
    timestamps: list[datetime],
    model_C: dict[str, np.ndarray],
    ercot_C: dict[str, np.ndarray],
    sp_ids: list[str],
    ref_methods: list[str],
    strategy: str = "max_area",
    min_sp_fraction: float = 0.90,
) -> tuple[
    list[datetime], dict[str, np.ndarray], dict[str, np.ndarray], list[str],
]:
    """Pick the largest dense (SP subset × hour subset) rectangle.

    SPs come online throughout the year (batteries, solar), so the old
    "drop any hour where any SP is NaN" rule sacrificed most of the window
    to preserve every SP. This sweep instead trades a small number of
    late-arriving SPs for a much larger hour axis.

    Strategy:
    * ``max_area`` (default) — argmax over ``k * n_hours_kept(k)``, with a
      floor of ``min_sp_fraction * n_sp`` on kept SPs so we never strip the
      row axis too far to chase hours.
    * ``max_hours`` — maximize hours kept subject to the same floor.
    * ``threshold`` — keep all SPs, prune hours before the last SP's
      first-dense hour. Reproduces the pre-fix all-or-nothing behavior.

    The output rectangle is fully dense; downstream code sees no NaN cells
    that weren't already method-specific.
    """
    if strategy not in SP_COVERAGE_STRATEGIES:
        raise ValueError(
            f"unknown sp-coverage strategy: {strategy!r} "
            f"(expected one of {SP_COVERAGE_STRATEGIES})"
        )
    if not ref_methods:
        return timestamps, model_C, ercot_C, sp_ids

    n_hours = len(timestamps)
    n_sp = len(sp_ids)
    if n_hours == 0 or n_sp == 0:
        return timestamps, model_C, ercot_C, sp_ids

    bus_missing = _structural_missing(model_C, ref_methods)   # (n_bus, n_hours)
    sp_missing = _structural_missing(ercot_C, ref_methods)    # (n_sp, n_hours)

    sp_first_dense = _first_dense_hour(sp_missing)
    bus_first_dense = _first_dense_hour(bus_missing)
    bus_hour_cutoff = int(bus_first_dense.max()) if bus_first_dense.size else 0

    # Sort SPs by first-dense hour ascending; keep the k earliest to emerge.
    sp_order = np.argsort(sp_first_dense, kind="stable")
    sorted_first_dense = sp_first_dense[sp_order]

    # k = number of SPs kept, 1..n_sp.
    hour_cutoffs = np.maximum(sorted_first_dense, bus_hour_cutoff)
    hours_kept = np.clip(n_hours - hour_cutoffs, 0, None)
    k_range = np.arange(1, n_sp + 1)
    areas = k_range * hours_kept

    min_k = max(1, int(np.ceil(min_sp_fraction * n_sp)))
    if strategy == "threshold":
        k_sel = n_sp
    else:
        elig = k_range >= min_k
        # Guaranteed non-empty since min_k <= n_sp.
        scores = areas if strategy == "max_area" else hours_kept
        elig_scores = np.where(elig, scores, -1)
        k_sel = int(k_range[np.argmax(elig_scores)])

    kept_sp_positions = sp_order[:k_sel]
    dropped_sp_positions = sp_order[k_sel:]
    dropped_sp_ids = [sp_ids[i] for i in dropped_sp_positions]

    _log_sweep(
        sorted_first_dense, hours_kept, areas, k_sel,
        timestamps, dropped_sp_ids, strategy, min_sp_fraction,
    )

    hour_cutoff_sel = int(hour_cutoffs[k_sel - 1])
    if k_sel == n_sp and hour_cutoff_sel == 0:
        return timestamps, model_C, ercot_C, sp_ids

    kept_sp_mask = np.zeros(n_sp, dtype=bool)
    kept_sp_mask[kept_sp_positions] = True
    for m in ref_methods:
        model_C[m] = model_C[m][:, hour_cutoff_sel:]
        ercot_C[m] = ercot_C[m][kept_sp_mask][:, hour_cutoff_sel:]
    new_sp_ids = [sp for sp, keep in zip(sp_ids, kept_sp_mask) if keep]
    new_timestamps = timestamps[hour_cutoff_sel:]
    return new_timestamps, model_C, ercot_C, new_sp_ids


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
    ap.add_argument('--sp-coverage-strategy', default='max_area',
                    choices=list(SP_COVERAGE_STRATEGIES),
                    help='How to trade SPs against hours when picking the '
                         'dense rectangle. threshold reproduces the pre-fix '
                         'all-or-nothing behavior. (default: max_area)')
    ap.add_argument('--min-sp-fraction', type=float, default=0.90,
                    help='Floor on the fraction of SPs kept by max_area / '
                         'max_hours strategies (default: 0.90).')
    args = ap.parse_args()

    if not 0.0 <= args.min_sp_fraction <= 1.0:
        raise SystemExit("--min-sp-fraction must be in [0.0, 1.0]")

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

        timestamps, model_C, ercot_C, sp_ids = _select_dense_rectangle(
            timestamps, model_C, ercot_C, sp_ids, args.ref_methods,
            strategy=args.sp_coverage_strategy,
            min_sp_fraction=args.min_sp_fraction,
        )

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
