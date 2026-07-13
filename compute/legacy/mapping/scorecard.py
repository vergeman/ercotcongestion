"""
0047 — zone-aggregated scorecard.

For a chosen derived-zone partition (`ref × algo × K`), aggregate the
model-side congestion matrix and the ERCOT-side congestion matrix into
per-zone hourly series, then score how well the model tracks ERCOT.

SP → zone comes from CM.1 (`sp_id → best_bus`) joined against the
model-side clustering artifact (`bus_id → cluster_id`). Buses use the
same clustering artifact directly. This is the behavioral tag path —
not point-in-polygon — retired by CM.4/CM.5.

Headline `zone_rank_spearman_per_hour` is a per-hour spatial rank
across cluster means. For per-SP temporal rank correlation, see
`mapping_correlation_summary_<run_id>.json::median_spearman`.

Reads:
  * `runs/<run_id>/matrix/congestion_matrices.npz`  (via CM.1 loader)
  * `runs/<run_id>/mapping/mapping_correlation_<run_id>.npz`
  * `runs/<run_id>/clustering/cluster_labels_<ref>_<algo>_k<K>.npz`

Writes (one file per cell — running with different (ref, algo, k) does
not overwrite; ``compute.promote`` picks a cell to serve by symlinking
``mapping/scorecard.json`` at the chosen file):
  * `runs/<run_id>/mapping/scorecard_<run_id>_<ref>_<algo>_k<K>.json`
  * `runs/<run_id>/mapping/scorecard_series_<run_id>_<ref>_<algo>_k<K>.npz`

Usage:
    python -m compute.legacy.mapping.scorecard --run-id v1-120 \
        [--ref kkt_perbus] \
        [--algo hierarchical_on_beta] [--k 6] \
        [--deadband 2.0] [--min-members 3]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from compute.legacy.mapping.correlation_map import (
    DEFAULT_ERCOT_REF,
    DEFAULT_MODEL_REF,
    RUNS_ROOT,
    load_matrices,
)

DEFAULT_ALGO = "hierarchical_on_beta"
DEFAULT_K = 6
DEFAULT_DEADBAND = 2.0
DEFAULT_MIN_MEMBERS = 3
OUTLIER_Z_THRESHOLD = 2.0


def _mapping_dir(run_id: str) -> Path:
    return RUNS_ROOT / run_id / "mapping"


def _clustering_dir(run_id: str) -> Path:
    return RUNS_ROOT / run_id / "clustering"


def load_partition(
    run_id: str,
    ref: str,
    algo: str,
    k: int,
) -> tuple[dict[str, int], dict[str, int]]:
    """Load `bus_id → cluster_id` and derive `sp_id → cluster_id`.

    Buses come straight from the clustering artifact. SPs are tagged via
    CM.1: each SP's `best_bus` is looked up in the bus→cluster map. SPs
    whose best_bus is not in the map (dropped in clustering prefilter,
    or missing) are omitted from the result.

    Fails with a clear message if either artifact is missing.
    """
    labels_path = _clustering_dir(run_id) / f"cluster_labels_{ref}_{algo}_k{k}.npz"
    if not labels_path.exists():
        raise SystemExit(
            f"cluster labels not found: {labels_path}\n"
            f"run the post-CM.6 sweep first: "
            f"python -m compute.legacy.clustering.runner --run-id {run_id} "
            f"--coords-model <path> --algos {algo} --ks {k}"
        )
    with np.load(labels_path) as z:
        bus_ids = z["bus_id"].astype(str)
        cluster_ids = z["cluster_id"].astype(int)
    bus_to_cluster = {str(b): int(c) for b, c in zip(bus_ids, cluster_ids)}

    corr_path = _mapping_dir(run_id) / f"mapping_correlation_{run_id}.npz"
    if not corr_path.exists():
        raise SystemExit(
            f"CM.1 mapping not found: {corr_path}\n"
            f"run: python -m compute.legacy.mapping.correlation_map --run-id {run_id}"
        )
    with np.load(corr_path) as z:
        sp_ids = z["sp_id"].astype(str)
        best_bus = z["best_bus"].astype(str)
    sp_to_cluster: dict[str, int] = {}
    for sp, bb in zip(sp_ids, best_bus):
        c = bus_to_cluster.get(str(bb))
        if c is not None:
            sp_to_cluster[str(sp)] = int(c)

    return bus_to_cluster, sp_to_cluster


def aggregate(
    model_C: np.ndarray,
    ercot_C: np.ndarray,
    bus_ids: np.ndarray,
    sp_ids: np.ndarray,
    bus_to_cluster: dict[str, int],
    sp_to_cluster: dict[str, int],
    min_members: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """Group-mean model_C over buses and ercot_C over SPs by cluster_id.

    Zones present on only one side, or with fewer than `min_members` on
    either side, are dropped and reported in warnings.

    Returns (cluster_ids, model_Z, ercot_Z, n_buses, n_sps, warnings)
    where `model_Z` and `ercot_Z` are (n_hours, n_zones) with columns
    aligned to `cluster_ids`.
    """
    n_hours = model_C.shape[1]
    warnings: list[str] = []

    bus_zone = np.array(
        [bus_to_cluster.get(str(b), -1) for b in bus_ids], dtype=int,
    )
    sp_zone = np.array(
        [sp_to_cluster.get(str(s), -1) for s in sp_ids], dtype=int,
    )

    n_bus_untagged = int((bus_zone == -1).sum())
    n_sp_untagged = int((sp_zone == -1).sum())
    if n_bus_untagged:
        warnings.append(f"{n_bus_untagged} model buses had no cluster tag (dropped)")
    if n_sp_untagged:
        warnings.append(f"{n_sp_untagged} SPs had no cluster tag (dropped)")

    zones_bus = set(int(z) for z in np.unique(bus_zone) if z != -1)
    zones_sp = set(int(z) for z in np.unique(sp_zone) if z != -1)
    shared = sorted(zones_bus & zones_sp)
    only_bus = sorted(zones_bus - zones_sp)
    only_sp = sorted(zones_sp - zones_bus)
    if only_bus:
        warnings.append(f"zones with buses but no SPs: {only_bus}")
    if only_sp:
        warnings.append(f"zones with SPs but no buses: {only_sp}")

    kept: list[int] = []
    model_cols: list[np.ndarray] = []
    ercot_cols: list[np.ndarray] = []
    n_buses: list[int] = []
    n_sps: list[int] = []
    for z in shared:
        bmask = bus_zone == z
        smask = sp_zone == z
        nb = int(bmask.sum())
        ns = int(smask.sum())
        if nb < min_members or ns < min_members:
            warnings.append(
                f"zone {z} dropped: n_buses={nb}, n_sps={ns} (< {min_members})"
            )
            continue
        kept.append(z)
        model_cols.append(model_C[bmask].mean(axis=0))
        ercot_cols.append(ercot_C[smask].mean(axis=0))
        n_buses.append(nb)
        n_sps.append(ns)

    if not kept:
        return (
            np.empty((0,), dtype=int),
            np.empty((n_hours, 0), dtype=float),
            np.empty((n_hours, 0), dtype=float),
            np.empty((0,), dtype=int),
            np.empty((0,), dtype=int),
            warnings,
        )

    cluster_ids = np.array(kept, dtype=int)
    model_Z = np.stack(model_cols, axis=1)  # (n_hours, n_zones)
    ercot_Z = np.stack(ercot_cols, axis=1)
    return (
        cluster_ids,
        model_Z,
        ercot_Z,
        np.array(n_buses, dtype=int),
        np.array(n_sps, dtype=int),
        warnings,
    )


def _pearson_columns(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Per-column Pearson correlation between two (n_hours, n_col) arrays."""
    if a.size == 0 or a.shape[0] < 2:
        return np.full(a.shape[1], np.nan)
    am = a - a.mean(axis=0, keepdims=True)
    bm = b - b.mean(axis=0, keepdims=True)
    denom = np.sqrt((am * am).sum(axis=0) * (bm * bm).sum(axis=0))
    with np.errstate(divide="ignore", invalid="ignore"):
        out = (am * bm).sum(axis=0) / denom
    return np.where(denom > 0, out, np.nan)


def _sign_agreement(a: np.ndarray, b: np.ndarray, deadband: float) -> np.ndarray:
    """Per-column fraction where sign(a)==sign(b), with a ±deadband band.

    Rows where |a| <= deadband OR |b| <= deadband are excluded from
    both numerator and denominator. Returns NaN for columns with no
    eligible rows.
    """
    eligible = (np.abs(a) > deadband) & (np.abs(b) > deadband)
    agree = eligible & ((a > 0) == (b > 0))
    n = eligible.sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = agree.sum(axis=0) / n
    return np.where(n > 0, out, np.nan)


def _zone_rank_spearman_per_hour(model_Z: np.ndarray, ercot_Z: np.ndarray) -> np.ndarray:
    """Per-hour Spearman across zones = Pearson on ranks across the zone axis.

    Skips hours where either side is constant (rank correlation undefined).
    Ties broken by scipy-style average ranks via numpy.argsort-of-argsort.
    """
    n_hours, n_zones = model_Z.shape
    if n_zones < 2:
        return np.full(n_hours, np.nan)
    out = np.full(n_hours, np.nan)
    for t in range(n_hours):
        m = model_Z[t]
        e = ercot_Z[t]
        if not (np.isfinite(m).all() and np.isfinite(e).all()):
            continue
        rm = np.argsort(np.argsort(m))
        re = np.argsort(np.argsort(e))
        rm_z = rm - rm.mean()
        re_z = re - re.mean()
        denom = np.sqrt((rm_z ** 2).sum() * (re_z ** 2).sum())
        if denom > 0:
            out[t] = float((rm_z * re_z).sum() / denom)
    return out


def score(
    model_Z: np.ndarray,
    ercot_Z: np.ndarray,
    deadband: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, float]]:
    """Per-zone corr + sign_agreement; headline rank Spearman.

    Returns (corr_per_zone, sign_per_zone, spearman_per_hour, headline).
    """
    corr = _pearson_columns(model_Z, ercot_Z)
    sign = _sign_agreement(model_Z, ercot_Z, deadband)
    spearman = _zone_rank_spearman_per_hour(model_Z, ercot_Z)
    finite_sp = spearman[np.isfinite(spearman)]
    finite_corr = corr[np.isfinite(corr)]
    finite_sign = sign[np.isfinite(sign)]
    headline = {
        "zone_rank_spearman_per_hour": float(finite_sp.mean()) if finite_sp.size else None,
        "mean_corr": float(finite_corr.mean()) if finite_corr.size else None,
        "mean_sign_agreement": float(finite_sign.mean()) if finite_sign.size else None,
        "n_hours": int(model_Z.shape[0]),
        "n_zones": int(model_Z.shape[1]),
    }
    return corr, sign, spearman, headline


def dispersion(
    model_C: np.ndarray,
    ercot_C: np.ndarray,
    bus_ids: np.ndarray,
    sp_ids: np.ndarray,
    bus_to_cluster: dict[str, int],
    sp_to_cluster: dict[str, int],
    cluster_ids: np.ndarray,
    ercot_Z: np.ndarray,
) -> list[dict]:
    """Within-zone spread of per-member vs ercot_Z correlation.

    For each kept zone Z: correlate each member (buses on the model side,
    SPs on the ERCOT side) against `ercot_Z[:, Z]`; report std of those
    correlations and the ids whose |z-score| exceeds `OUTLIER_Z_THRESHOLD`.
    """
    out: list[dict] = []
    for col, z in enumerate(cluster_ids.tolist()):
        ez = ercot_Z[:, col:col + 1]  # (n_hours, 1)

        bmask = np.array(
            [bus_to_cluster.get(str(b), -1) == z for b in bus_ids],
        )
        smask = np.array(
            [sp_to_cluster.get(str(s), -1) == z for s in sp_ids],
        )

        m_corrs = _pearson_columns(model_C[bmask].T, np.tile(ez, (1, int(bmask.sum()))))
        s_corrs = _pearson_columns(ercot_C[smask].T, np.tile(ez, (1, int(smask.sum()))))

        outliers_model = _find_outliers(m_corrs, bus_ids[bmask])
        outliers_ercot = _find_outliers(s_corrs, sp_ids[smask])

        out.append({
            "cluster_id": int(z),
            "model_side_std": _finite_std(m_corrs),
            "ercot_side_std": _finite_std(s_corrs),
            "outlier_buses": outliers_model,
            "outlier_sps": outliers_ercot,
        })
    return out


def _finite_std(x: np.ndarray) -> float | None:
    x = x[np.isfinite(x)]
    return float(x.std(ddof=0)) if x.size >= 2 else None


def _find_outliers(x: np.ndarray, ids: np.ndarray) -> list[str]:
    mask = np.isfinite(x)
    if mask.sum() < 2:
        return []
    mu = x[mask].mean()
    sd = x[mask].std(ddof=0)
    if sd == 0:
        return []
    z = (x - mu) / sd
    flagged = mask & (np.abs(z) > OUTLIER_Z_THRESHOLD)
    return [str(i) for i in ids[flagged]]


def _write_outputs(
    run_id: str,
    ref: str,
    algo: str,
    k: int,
    deadband: float,
    min_members: int,
    hours: np.ndarray,
    cluster_ids: np.ndarray,
    model_Z: np.ndarray,
    ercot_Z: np.ndarray,
    n_buses: np.ndarray,
    n_sps: np.ndarray,
    corr_per_zone: np.ndarray,
    sign_per_zone: np.ndarray,
    spearman_per_hour: np.ndarray,
    headline: dict,
    dispersion_rows: list[dict],
    warnings: list[str],
) -> tuple[Path, Path]:
    out_dir = _mapping_dir(run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    cell = f"{run_id}_{ref}_{algo}_k{int(k)}"
    json_path = out_dir / f"scorecard_{cell}.json"
    npz_path = out_dir / f"scorecard_series_{cell}.npz"

    zones = []
    for i, z in enumerate(cluster_ids.tolist()):
        disp = dispersion_rows[i]
        zones.append({
            "cluster_id": int(z),
            "n_buses": int(n_buses[i]),
            "n_sps": int(n_sps[i]),
            "corr": _nan_to_none(corr_per_zone[i]),
            "sign_agreement": _nan_to_none(sign_per_zone[i]),
            "model_side_std": disp["model_side_std"],
            "ercot_side_std": disp["ercot_side_std"],
            "outlier_buses": disp["outlier_buses"],
            "outlier_sps": disp["outlier_sps"],
        })

    payload = {
        "run_id": run_id,
        "params": {
            "ref": ref,
            "algo": algo,
            "k": int(k),
            "deadband": float(deadband),
            "min_members": int(min_members),
        },
        "headline": headline,
        "zones": zones,
        "warnings": warnings,
    }
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)

    np.savez_compressed(
        npz_path,
        hours=hours.astype(str),
        cluster_ids=cluster_ids.astype(np.int64),
        model_Z=model_Z.astype(float),
        ercot_Z=ercot_Z.astype(float),
        spearman_per_hour=spearman_per_hour.astype(float),
    )
    return json_path, npz_path


def _nan_to_none(x: float) -> float | None:
    return None if not np.isfinite(x) else float(x)


def _build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Aggregate model and ERCOT congestion by derived zone and score.",
    )
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--ref", default=DEFAULT_MODEL_REF,
                    help=f"Reference method for the partition (default {DEFAULT_MODEL_REF}).")
    ap.add_argument("--model-ref", default=DEFAULT_MODEL_REF)
    ap.add_argument("--ercot-ref", default=DEFAULT_ERCOT_REF)
    ap.add_argument("--algo", default=DEFAULT_ALGO)
    ap.add_argument("--k", type=int, default=DEFAULT_K)
    ap.add_argument("--deadband", type=float, default=DEFAULT_DEADBAND,
                    help=f"$/MWh deadband for sign agreement (default {DEFAULT_DEADBAND}).")
    ap.add_argument("--min-members", type=int, default=DEFAULT_MIN_MEMBERS,
                    help=f"Skip zones with fewer members on either side (default {DEFAULT_MIN_MEMBERS}).")
    return ap


def main(argv: list[str] | None = None) -> None:
    args = _build_argparser().parse_args(argv)

    model_C, ercot_C, bus_ids, sp_ids, hours = load_matrices(
        args.run_id, model_ref=args.model_ref, ercot_ref=args.ercot_ref,
    )
    print(f"run_id={args.run_id} ref={args.ref} algo={args.algo} k={args.k}")
    print(f"model_C={model_C.shape} ercot_C={ercot_C.shape} hours={hours.shape[0]}")

    bus_to_cluster, sp_to_cluster = load_partition(
        args.run_id, args.ref, args.algo, args.k,
    )
    print(f"partition: {len(bus_to_cluster)} buses tagged, "
          f"{len(sp_to_cluster)} SPs tagged via CM.1 best_bus")

    cluster_ids, model_Z, ercot_Z, n_buses, n_sps, warns = aggregate(
        model_C, ercot_C, bus_ids, sp_ids,
        bus_to_cluster, sp_to_cluster,
        args.min_members,
    )
    print(f"kept zones: {cluster_ids.tolist()}")
    for w in warns:
        print(f"  warn: {w}")

    corr, sign, spearman, headline = score(model_Z, ercot_Z, args.deadband)
    disp = dispersion(
        model_C, ercot_C, bus_ids, sp_ids,
        bus_to_cluster, sp_to_cluster,
        cluster_ids, ercot_Z,
    )

    json_path, npz_path = _write_outputs(
        run_id=args.run_id, ref=args.ref, algo=args.algo, k=args.k,
        deadband=args.deadband, min_members=args.min_members,
        hours=hours, cluster_ids=cluster_ids,
        model_Z=model_Z, ercot_Z=ercot_Z,
        n_buses=n_buses, n_sps=n_sps,
        corr_per_zone=corr, sign_per_zone=sign,
        spearman_per_hour=spearman, headline=headline,
        dispersion_rows=disp, warnings=warns,
    )
    print(f"wrote {json_path}")
    print(f"wrote {npz_path}")
    rs = headline["zone_rank_spearman_per_hour"]
    mc = headline["mean_corr"]
    ms = headline["mean_sign_agreement"]
    print(
        f"headline: zone_rank_spearman_per_hour={rs:.3f} mean_corr={mc:.3f} "
        f"mean_sign_agreement={ms:.3f} (n_hours={headline['n_hours']}, "
        f"n_zones={headline['n_zones']})"
        if rs is not None else "headline: no finite metrics"
    )


if __name__ == "__main__":
    main()
