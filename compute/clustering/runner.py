"""(ref × algo × K) clustering sweep over a 0016 npz.

Composition layer over 0017 (algorithms), 0018 (diagnostics), and 0019
(polygons + transfer). Reads the bus×hour matrices persisted by 0016 for
each ref method, runs every requested (algo, K) on the model side, builds
zone polygons, transfers labels to ERCOT settlement points, and emits a
summary JSON plus per-cell GeoJSON and ERCOT label CSV.

CLI::

    python -m compute.clustering.runner \
        --matrices <npz> \
        --coords-model <bus_coords.csv> \
        --coords-ercot <settlement_points_geocoded.csv> \
        --out-dir <dir>

Cells with empty matrices ((0, 0) shape — three one-sided ref/side combos
in the current npz) are skipped at load time. Cells whose algo raises log
a structured `FAIL` line and emit a `status="failed"` summary row.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from .algorithm import (
    hierarchical_corr,
    hybrid_geo,
    kmeans_vec,
    pca_kmeans,
    spectral_corr,
)
from .diagnostics import (
    cluster_stability_ari,
    silhouette,
    spatial_coherence,
    within_cluster_variance,
)
from .polygons import (
    build_polygons,
    transfer_labels,
    write_zones_geojson,
)

log = logging.getLogger("compute.clustering.runner")

BASE_DIR = Path(__file__).parent
RUNS_ROOT = BASE_DIR.parent / "runs"

ALGOS: dict[str, Callable] = {
    "hierarchical_corr": hierarchical_corr,
    "kmeans_vec": kmeans_vec,
    "spectral_corr": spectral_corr,
    "pca_kmeans": pca_kmeans,
    "hybrid_geo": hybrid_geo,
}

DEFAULT_KS = [4, 6, 8, 10, 12, 16]


def _list_arg(s: str | None) -> list[str] | None:
    if s is None:
        return None
    return [tok.strip() for tok in s.split(",") if tok.strip()]


def _int_list_arg(s: str | None) -> list[int] | None:
    parts = _list_arg(s)
    if parts is None:
        return None
    return [int(p) for p in parts]


def _discover_refs(npz: np.lib.npyio.NpzFile) -> list[str]:
    """All ref method names present as `<ref>_model_C` or `<ref>_ercot_C` keys."""
    refs: set[str] = set()
    for k in npz.files:
        if k.endswith("_model_C"):
            refs.add(k[: -len("_model_C")])
        elif k.endswith("_ercot_C"):
            refs.add(k[: -len("_ercot_C")])
    return sorted(refs)


def _load_matrices(
    npz_path: Path,
    ref_methods: list[str] | None,
) -> dict[str, dict[str, pd.DataFrame]]:
    """Rehydrate per-(ref, side) `pd.DataFrame`s from the 0016 npz.

    Empty `(0, 0)` matrices are skipped-and-logged here so the sweep loop
    only ever sees usable cells.
    """
    npz = np.load(npz_path, allow_pickle=False)
    available = _discover_refs(npz)
    refs = ref_methods or available
    missing = [r for r in refs if r not in available]
    if missing:
        raise SystemExit(
            f"ref methods missing from {npz_path.name}: {missing}; "
            f"available = {available}"
        )

    out: dict[str, dict[str, pd.DataFrame]] = {}
    for ref in refs:
        sides: dict[str, pd.DataFrame] = {}
        for side, id_key in (("model", "bus_ids"), ("ercot", "sp_ids")):
            C = npz[f"{ref}_{side}_C"]
            ids = npz[f"{ref}_{side}_{id_key}"]
            hours = npz[f"{ref}_{side}_hours"]
            if C.size == 0:
                log.info("SKIP %s/%s: empty matrix", ref, side)
                continue
            sides[side] = pd.DataFrame(
                C, index=pd.Index(ids, name="id"), columns=hours,
            )
        if sides:
            out[ref] = sides
    return out


def _load_coords(path: Path, id_col: str) -> pd.DataFrame:
    """Load a `[id, lat, lon]` CSV and index by `id` (coerced to str)."""
    df = pd.read_csv(path, usecols=[id_col, "lat", "lon"])
    df[id_col] = df[id_col].astype(str)
    df = df.dropna(subset=["lat", "lon"]).drop_duplicates(subset=[id_col])
    return df.set_index(id_col)[["lat", "lon"]]


def _safe(fn: Callable, *args, **kwargs) -> float:
    """Wrap a diagnostic call so a failure becomes NaN, not a sweep crash."""
    try:
        v = fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        log.warning("diagnostic %s failed: %s", fn.__name__, exc)
        return float("nan")
    return float(v) if v is not None else float("nan")


def _algo_kwargs(algo: str, coords_model: pd.DataFrame, seed: int, alpha: float | None) -> dict[str, Any]:
    """Per-algo kwargs the sweep loop injects (not user-controlled)."""
    if algo == "hybrid_geo":
        kwargs: dict[str, Any] = {"coords": coords_model, "seed": seed}
        if alpha is not None:
            kwargs["alpha"] = alpha
        return kwargs
    if algo in ("kmeans_vec", "spectral_corr", "pca_kmeans"):
        return {"seed": seed}
    return {}


def _run_cell(
    ref: str,
    algo: str,
    K: int,
    sides: dict[str, pd.DataFrame],
    coords_model: pd.DataFrame,
    coords_ercot: pd.DataFrame,
    out_dir: Path,
    seed: int,
    alpha: float | None,
) -> dict[str, Any]:
    """Run one (ref, algo, K) cell. Returns a summary row."""
    t0 = time.perf_counter()
    row: dict[str, Any] = {
        "ref": ref,
        "algo": algo,
        "K": K,
        "n_buses_model": None,
        "n_sps_ercot": None,
        "n_polygons": None,
        "sil_model": None,
        "stab_model": None,
        "wcv_model": None,
        "sc_model": None,
        "sil_ercot": None,
        "wcv_ercot": None,
        "sc_ercot": None,
        "elapsed_s": None,
        "status": "ok",
        "error": None,
    }

    C_model = sides.get("model")
    if C_model is None:
        row["status"] = "skip"
        row["error"] = "no model-side matrix"
        log.info("SKIP %s/%s/K=%d: %s", ref, algo, K, row["error"])
        return row

    row["n_buses_model"] = int(C_model.shape[0])
    algo_fn = ALGOS[algo]
    a_kwargs = _algo_kwargs(algo, coords_model, seed, alpha)

    try:
        labels_model = algo_fn(C_model, K, **a_kwargs)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "FAIL %s/%s/K=%d: %s: %s", ref, algo, K, type(exc).__name__, exc,
        )
        row["status"] = "failed"
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["elapsed_s"] = round(time.perf_counter() - t0, 3)
        return row

    row["sil_model"] = _safe(silhouette, C_model, labels_model)
    # cluster_stability_ari injects `seed` itself when the algo accepts it,
    # so drop our copy to avoid a duplicate-keyword TypeError.
    stab_kwargs = {k: v for k, v in a_kwargs.items() if k != "seed"}
    row["stab_model"] = _safe(
        cluster_stability_ari, C_model, algo_fn, K, seed=seed, **stab_kwargs,
    )
    row["wcv_model"] = _safe(within_cluster_variance, C_model, labels_model)
    row["sc_model"] = _safe(spatial_coherence, labels_model, coords_model)

    try:
        polygons = build_polygons(labels_model, coords_model, alpha=alpha)
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "FAIL %s/%s/K=%d build_polygons: %s: %s",
            ref, algo, K, type(exc).__name__, exc,
        )
        row["status"] = "failed"
        row["error"] = f"build_polygons: {type(exc).__name__}: {exc}"
        row["elapsed_s"] = round(time.perf_counter() - t0, 3)
        return row

    row["n_polygons"] = int(len(polygons))
    if polygons.empty:
        log.info(
            "SKIP %s/%s/K=%d: build_polygons produced no polygons", ref, algo, K,
        )
        row["status"] = "no_polygons"
        row["elapsed_s"] = round(time.perf_counter() - t0, 3)
        return row

    geojson_path = out_dir / f"zones_{ref}_{algo}_k{K}.geojson"
    write_zones_geojson(polygons, geojson_path)

    C_ercot = sides.get("ercot")
    if C_ercot is not None:
        row["n_sps_ercot"] = int(C_ercot.shape[0])
        labels_ercot = transfer_labels(polygons, coords_ercot)
        # Persist all transferred labels, including SPs not in C_ercot.
        label_csv = out_dir / f"ercot_sp_labels_{ref}_{algo}_k{K}.csv"
        out_df = labels_ercot.rename("cluster_id").reset_index()
        if out_df.columns[0] != "settlement_point":
            out_df = out_df.rename(columns={out_df.columns[0]: "settlement_point"})
        out_df.to_csv(label_csv, index=False)

        # Cross-source diagnostics on the ERCOT matrix using transferred labels.
        common = C_ercot.index.intersection(labels_ercot.index)
        if len(common) > 0:
            row["sil_ercot"] = _safe(
                silhouette, C_ercot.loc[common], labels_ercot.loc[common],
            )
            row["wcv_ercot"] = _safe(
                within_cluster_variance,
                C_ercot.loc[common],
                labels_ercot.loc[common],
            )
            row["sc_ercot"] = _safe(
                spatial_coherence,
                labels_ercot.loc[common],
                coords_ercot,
            )

    row["elapsed_s"] = round(time.perf_counter() - t0, 3)
    return row


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run-id", default=None,
                   help="Run identifier. When set, --matrices and --out-dir "
                        "are derived from compute/runs/<run_id>/{matrix,clustering}/.")
    p.add_argument("--matrices", default=None, type=Path,
                   help="Explicit path to congestion_matrices npz. Required when "
                        "--run-id is not set; wins over --run-id derivation when both given.")
    p.add_argument("--coords-model", required=True, type=Path)
    p.add_argument("--coords-ercot", required=True, type=Path)
    p.add_argument("--out-dir", default=None, type=Path,
                   help="Explicit output directory. Required when --run-id is not "
                        "set; wins over --run-id derivation when both given.")
    p.add_argument("--ref-methods", default=None, help="comma list; default = all in npz")
    p.add_argument("--algos", default=None, help="comma list; default = all five")
    p.add_argument("--ks", default=None, help="comma list of ints; default = 4,6,8,10,12,16")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument(
        "--alpha", type=float, default=None,
        help="Concave-hull ratio passed to build_polygons and hybrid_geo; "
             "omit for convex hull only.",
    )
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    matrices_path = args.matrices
    out_dir = args.out_dir
    if args.run_id is not None:
        if matrices_path is None:
            matrices_path = RUNS_ROOT / args.run_id / "matrix" / "congestion_matrices.npz"
        if out_dir is None:
            out_dir = RUNS_ROOT / args.run_id / "clustering"
        run_id = args.run_id
    else:
        if matrices_path is None or out_dir is None:
            raise SystemExit("must pass --run-id, or both --matrices and --out-dir")
        run_id = matrices_path.stem.removeprefix("congestion_matrices_")

    out_dir.mkdir(parents=True, exist_ok=True)

    refs_arg = _list_arg(args.ref_methods)
    algos = _list_arg(args.algos) or list(ALGOS.keys())
    unknown = [a for a in algos if a not in ALGOS]
    if unknown:
        raise SystemExit(f"unknown algos: {unknown}; known = {list(ALGOS)}")
    ks = _int_list_arg(args.ks) or DEFAULT_KS

    matrices = _load_matrices(matrices_path, refs_arg)
    coords_model = _load_coords(args.coords_model, id_col="bus")
    coords_ercot = _load_coords(args.coords_ercot, id_col="settlement_point")

    rows: list[dict[str, Any]] = []
    for ref, sides in matrices.items():
        for algo in algos:
            for K in ks:
                rows.append(_run_cell(
                    ref=ref, algo=algo, K=K, sides=sides,
                    coords_model=coords_model, coords_ercot=coords_ercot,
                    out_dir=out_dir, seed=args.seed, alpha=args.alpha,
                ))

    summary = {
        "run_id": run_id,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "params": {
            "matrices": str(matrices_path),
            "coords_model": str(args.coords_model),
            "coords_ercot": str(args.coords_ercot),
            "ref_methods": list(matrices.keys()),
            "algos": algos,
            "ks": ks,
            "seed": args.seed,
            "alpha": args.alpha,
        },
        "rows": rows,
    }
    summary_name = "summary.json" if args.run_id is not None else f"clustering_summary_{run_id}.json"
    summary_path = out_dir / summary_name
    with summary_path.open("w") as f:
        json.dump(summary, f, indent=2, default=_json_default)
    log.info(
        "wrote %s (rows=%d, ok=%d, failed=%d, skip=%d)",
        summary_path,
        len(rows),
        sum(1 for r in rows if r["status"] == "ok"),
        sum(1 for r in rows if r["status"] == "failed"),
        sum(1 for r in rows if r["status"] not in ("ok", "failed")),
    )
    return 0


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        v = float(o)
        return None if np.isnan(v) else v
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Path):
        return str(o)
    raise TypeError(f"not JSON-serializable: {type(o).__name__}")


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
