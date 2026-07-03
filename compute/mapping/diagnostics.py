"""
CM.4 — geo-vs-behavioral disagreement diagnostic.

One-shot report contrasting geographic containment (the pre-CM.1 way of
translating model clusters to ERCOT SPs) with correlation-based mapping
(CM.1). Kept as a diagnostic so we can quantify how much the geographic
assumption actually distorted the SP → cluster picture.

For a chosen partition (a zones GeoJSON produced by the clustering
sweep):

  * geo cluster for each SP    = `transfer_labels(polygons, coords_ercot)`
  * behavioral cluster for SP  = cluster of the SP's CM.1 `best_bus`,
                                 recovered by `transfer_labels(polygons,
                                 coords_model)` at that bus.

Reads:
  * `runs/<run_id>/mapping/mapping_correlation_<run_id>.npz`  (CM.1 output)
  * the partition GeoJSON passed via `--partition`

Writes:
  * `runs/<run_id>/mapping/geo_vs_behavioral_<run_id>.json` — summary
  * `runs/<run_id>/mapping/geo_vs_behavioral_<run_id>.npz` — per-SP records
    (unless `--no-per-sp`)

Usage:
    python -m compute.mapping.diagnostics --run-id v1-120 \\
        --partition compute/runs/v1-120/clustering/zones_<ref>_<algo>_k<K>.geojson \\
        [--coords-model ...] [--coords-ercot ...] [--no-per-sp]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from compute.clustering.polygons import transfer_labels

BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_ROOT = BASE_DIR / "runs"

DEFAULT_COORDS_MODEL = Path(
    "/data/processed/Texas2k_series25_case1_summerpeak_bus_coords.csv"
)
DEFAULT_COORDS_ERCOT = Path("/data/processed/settlement_points_geocoded.csv")


def _mapping_dir(run_id: str) -> Path:
    return RUNS_ROOT / run_id / "mapping"


def _load_coords(path: Path, id_col: str) -> pd.DataFrame:
    df = pd.read_csv(path, usecols=[id_col, "lat", "lon"])
    df[id_col] = df[id_col].astype(str)
    df = df.dropna(subset=["lat", "lon"]).drop_duplicates(subset=[id_col])
    return df.set_index(id_col)[["lat", "lon"]]


def _load_cm1_mapping(run_id: str) -> tuple[np.ndarray, np.ndarray]:
    """Return (sp_id, best_bus) from the CM.1 npz."""
    path = _mapping_dir(run_id) / f"mapping_correlation_{run_id}.npz"
    if not path.exists():
        raise SystemExit(f"CM.1 mapping not found: {path}")
    with np.load(path, allow_pickle=False) as z:
        sp_id = z["sp_id"].astype(str)
        best_bus = z["best_bus"].astype(str)
    return sp_id, best_bus


def geo_vs_behavioral_disagreement(
    run_id: str,
    partition_path: Path,
    coords_model_path: Path = DEFAULT_COORDS_MODEL,
    coords_ercot_path: Path = DEFAULT_COORDS_ERCOT,
    *,
    write_per_sp: bool = True,
) -> dict:
    """Compare geo-assigned vs behavioral cluster for every SP in CM.1.

    Behavioral cluster = the geographic cluster of the SP's CM.1
    `best_bus`. Geo cluster = point-in-polygon on the SP's own coord.
    The two agree iff geographic containment picks the same partition
    as behavioral correlation, which is exactly the assumption CM.1
    was introduced to stop relying on.

    Returns the summary dict and writes the JSON (+ npz when
    `write_per_sp`).
    """
    polygons = gpd.read_file(str(partition_path))
    if polygons.empty:
        raise SystemExit(f"partition has no polygons: {partition_path}")

    coords_model = _load_coords(coords_model_path, id_col="bus")
    coords_ercot = _load_coords(coords_ercot_path, id_col="settlement_point")

    sp_id, best_bus = _load_cm1_mapping(run_id)

    geo_sp = transfer_labels(polygons, coords_ercot)
    geo_bus = transfer_labels(polygons, coords_model)

    # Align per-SP: geo cluster from SP coords; behavioral cluster from
    # best_bus's own geo cluster. Rows where either side is missing get
    # dropped from the rate (surface counts separately).
    geo_cluster = geo_sp.reindex(pd.Index(sp_id)).to_numpy()
    behavioral_cluster = geo_bus.reindex(pd.Index(best_bus)).to_numpy()

    geo_missing = np.array([v is None or pd.isna(v) for v in geo_cluster])
    beh_missing = np.array([v is None or pd.isna(v) for v in behavioral_cluster])
    both_present = ~(geo_missing | beh_missing)

    # Coerce to int where present; use -1 sentinel elsewhere for the npz.
    def _fill_int(arr, present):
        out = np.full(arr.shape[0], -1, dtype=np.int64)
        out[present] = np.asarray(arr[present], dtype=np.int64)
        return out

    geo_int = _fill_int(geo_cluster, both_present | (~geo_missing))
    beh_int = _fill_int(behavioral_cluster, both_present | (~beh_missing))
    disagrees = np.where(both_present, geo_int != beh_int, False)

    n_sp = int(sp_id.shape[0])
    n_compared = int(both_present.sum())
    n_disagree = int(disagrees.sum())
    disagreement_rate = float(n_disagree / n_compared) if n_compared else None

    partition_id = Path(partition_path).stem
    summary = {
        "run_id": run_id,
        "partition_id": partition_id,
        "partition_path": str(partition_path),
        "n_sp": n_sp,
        "n_compared": n_compared,
        "n_disagree": n_disagree,
        "n_sp_missing_coords": int(geo_missing.sum()),
        "n_bus_missing_coords": int(beh_missing.sum()),
        "disagreement_rate": disagreement_rate,
    }

    out_dir = _mapping_dir(run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / f"geo_vs_behavioral_{run_id}.json"
    with summary_path.open("w") as f:
        json.dump(summary, f, indent=2)

    if write_per_sp:
        npz_path = out_dir / f"geo_vs_behavioral_{run_id}.npz"
        np.savez_compressed(
            npz_path,
            sp_id=sp_id,
            best_bus=best_bus,
            geo_cluster=geo_int,
            behavioral_cluster=beh_int,
            disagrees=disagrees,
        )

    return summary


def _build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Report geo-vs-behavioral SP→cluster disagreement.",
    )
    ap.add_argument("--run-id", required=True)
    ap.add_argument(
        "--partition", required=True, type=Path,
        help="Zones GeoJSON produced by the clustering sweep.",
    )
    ap.add_argument(
        "--coords-model", type=Path, default=DEFAULT_COORDS_MODEL,
        help=f"Bus coords CSV. Default: {DEFAULT_COORDS_MODEL}.",
    )
    ap.add_argument(
        "--coords-ercot", type=Path, default=DEFAULT_COORDS_ERCOT,
        help=f"Settlement-point coords CSV. Default: {DEFAULT_COORDS_ERCOT}.",
    )
    ap.add_argument(
        "--no-per-sp", action="store_true",
        help="Skip the per-SP npz; write only the summary JSON.",
    )
    return ap


def main(argv: list[str] | None = None) -> None:
    args = _build_argparser().parse_args(argv)
    summary = geo_vs_behavioral_disagreement(
        args.run_id,
        args.partition,
        coords_model_path=args.coords_model,
        coords_ercot_path=args.coords_ercot,
        write_per_sp=not args.no_per_sp,
    )
    rate = summary["disagreement_rate"]
    rate_str = f"{rate * 100:.1f}%" if rate is not None else "n/a"
    print(
        f"run_id={summary['run_id']} partition={summary['partition_id']}: "
        f"disagreement_rate={rate_str} "
        f"({summary['n_disagree']}/{summary['n_compared']} of "
        f"{summary['n_sp']} SPs)"
    )


if __name__ == "__main__":
    main()
