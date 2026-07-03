"""Render a chosen (ref, algo, K) partition as GeoJSON zones.

Loads `cluster_labels_<ref>_<algo>_k<K>.npz` from a sweep out-dir (or an
explicit `--labels` path), joins bus_id to a `bus_coords.csv`, and writes
one polygon per cluster.

CLI::

    python -m compute.clustering.render_partition \
        --run-id <id> --ref <name> --algo <name> --k <K> \
        --coords-model <bus_coords.csv> --out zones.geojson

Or with explicit labels npz::

    python -m compute.clustering.render_partition \
        --labels <path.npz> --coords-model <csv> --out <geojson>
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .polygons import build_polygons

log = logging.getLogger("compute.clustering.render_partition")

BASE_DIR = Path(__file__).parent
RUNS_ROOT = BASE_DIR.parent / "runs"


def _load_coords(path: Path, id_col: str = "bus") -> pd.DataFrame:
    df = pd.read_csv(path, usecols=[id_col, "lat", "lon"])
    df[id_col] = df[id_col].astype(str)
    df = df.dropna(subset=["lat", "lon"]).drop_duplicates(subset=[id_col])
    return df.set_index(id_col)[["lat", "lon"]]


def _load_labels(labels_path: Path) -> pd.Series:
    with np.load(labels_path, allow_pickle=False) as z:
        bus_id = np.asarray(z["bus_id"]).astype(str)
        cluster_id = np.asarray(z["cluster_id"]).astype(int)
    return pd.Series(
        cluster_id,
        index=pd.Index(bus_id, name="id"),
        name="cluster_id",
    )


def _resolve_labels_path(
    run_id: str | None,
    ref: str | None,
    algo: str | None,
    k: int | None,
    labels: Path | None,
) -> Path:
    if labels is not None:
        return labels
    if not (run_id and ref and algo and k is not None):
        raise SystemExit(
            "must pass --labels, or all of --run-id --ref --algo --k",
        )
    return (
        RUNS_ROOT / run_id / "clustering"
        / f"cluster_labels_{ref}_{algo}_k{k}.npz"
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run-id", default=None,
                   help="Sweep run id under compute/runs/. Combined with "
                        "--ref/--algo/--k, resolves the labels npz.")
    p.add_argument("--ref", default=None)
    p.add_argument("--algo", default=None)
    p.add_argument("--k", type=int, default=None)
    p.add_argument("--labels", default=None, type=Path,
                   help="Explicit labels npz. Wins over --run-id derivation.")
    p.add_argument("--coords-model", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument(
        "--alpha", type=float, default=None,
        help="Concave-hull ratio; omit for convex hull only.",
    )
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    labels_path = _resolve_labels_path(
        args.run_id, args.ref, args.algo, args.k, args.labels,
    )
    if not labels_path.exists():
        raise SystemExit(f"labels not found: {labels_path}")

    labels = _load_labels(labels_path)
    coords = _load_coords(args.coords_model, id_col="bus")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    polygons = build_polygons(labels, coords, alpha=args.alpha, out_path=args.out)

    if polygons.empty:
        log.warning("no polygons built from %s (all clusters had <3 points)", labels_path)
        return 1

    log.info("wrote %s (%d polygons)", args.out, len(polygons))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
