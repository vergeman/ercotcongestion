"""(algo × K) clustering sweep over a 0016 npz.

Composition layer over 0017 (algorithms) and 0018 (diagnostics). Reads the
model-side bus×hour matrix persisted by 0016 for the fixed reference
(`system_lambda_merit_order` — see CM.6), runs every requested (algo, K),
and emits a summary JSON plus per-cell `cluster_labels_<ref>_<algo>_k<K>.npz`
(arrays `bus_id`, `cluster_id`).

The reference-price axis was retired in CM.6: model-side congestion is
translation-invariant across the ref choice, so sweeping refs is redundant
work. The `<ref>` slot in output filenames is kept for continuity with
`render_partition` and downstream consumers.

Polygons are a rendering choice, not a sweep artifact — the sweep hot path
persists point-tags and defers polygon construction to
`compute.clustering.render_partition` for a chosen `(algo, K)`.

Geographic transfer of labels onto ERCOT settlement points is no longer
performed here — under CM.1/CM.2 the model→ERCOT translation is
correlation/basis-based, not spatial. `transfer_labels` remains
importable from `polygons` for one-shot diagnostics (see
`compute.mapping.diagnostics`).

CLI::

    python -m compute.clustering.runner \
        --matrices <npz> \
        --coords-model <bus_coords.csv> \
        --out-dir <dir>

Cells whose algo raises log a structured `FAIL` line and emit a
`status="failed"` summary row.
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
)
from .diagnostics import (
    cluster_stability_ari,
    silhouette,
    spatial_coherence,
    within_cluster_variance,
)

log = logging.getLogger("compute.clustering.runner")

BASE_DIR = Path(__file__).parent
RUNS_ROOT = BASE_DIR.parent / "runs"

DEFAULT_REF = "system_lambda_merit_order"

ALGOS: dict[str, Callable] = {
    "hierarchical_corr": hierarchical_corr,
    "kmeans_vec": kmeans_vec,
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


def _load_model_matrix(npz_path: Path, ref: str) -> pd.DataFrame:
    """Rehydrate the model-side `pd.DataFrame` for `ref` from the 0016 npz.

    Ercot-side matrices are no longer consumed by the sweep (CM.4 retired
    geo transfer; CM.6 fixes the ref axis on the model side).
    """
    npz = np.load(npz_path, allow_pickle=False)
    available = _discover_refs(npz)
    if ref not in available:
        raise SystemExit(
            f"ref '{ref}' missing from {npz_path.name}; available = {available}"
        )
    C = npz[f"{ref}_model_C"]
    if C.size == 0:
        raise SystemExit(
            f"model matrix for ref '{ref}' is empty in {npz_path.name}"
        )
    ids = npz[f"{ref}_model_bus_ids"]
    hours = npz[f"{ref}_model_hours"]
    return pd.DataFrame(C, index=pd.Index(ids, name="id"), columns=hours)


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
    if algo in ("kmeans_vec", "pca_kmeans"):
        return {"seed": seed}
    return {}


def _run_cell(
    ref: str,
    algo: str,
    K: int,
    C_model: pd.DataFrame,
    coords_model: pd.DataFrame,
    out_dir: Path,
    seed: int,
    alpha: float | None,
) -> dict[str, Any]:
    """Run one (algo, K) cell. Returns a summary row."""
    t0 = time.perf_counter()
    row: dict[str, Any] = {
        "ref": ref,
        "algo": algo,
        "K": K,
        "n_buses_model": int(C_model.shape[0]),
        "sil_model": None,
        "stab_model": None,
        "wcv_model": None,
        "sc_model": None,
        "elapsed_s": None,
        "status": "ok",
        "error": None,
    }
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

    labels_path = out_dir / f"cluster_labels_{ref}_{algo}_k{K}.npz"
    np.savez_compressed(
        labels_path,
        bus_id=np.asarray(labels_model.index, dtype=np.str_),
        cluster_id=np.asarray(labels_model.to_numpy(), dtype=np.int64),
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
    p.add_argument("--out-dir", default=None, type=Path,
                   help="Explicit output directory. Required when --run-id is not "
                        "set; wins over --run-id derivation when both given.")
    p.add_argument("--ref", default=DEFAULT_REF,
                   help=f"Reference-price method to load from the matrix npz "
                        f"(default {DEFAULT_REF}). Sweeping this axis was retired "
                        f"in CM.6; override only for testing / diagnostics.")
    p.add_argument("--ref-methods", default=None,
                   help="Deprecated (CM.6). Value is ignored — sweep is fixed on --ref.")
    p.add_argument("--algos", default=None, help="comma list; default = all four")
    p.add_argument("--ks", default=None, help="comma list of ints; default = 4,6,8,10,12,16")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument(
        "--alpha", type=float, default=None,
        help="Feature-vs-coord mixing weight for hybrid_geo; ignored by "
             "other algos. Polygons are not built here — see render_partition.",
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

    if args.ref_methods is not None:
        log.warning(
            "--ref-methods is deprecated (CM.6) and ignored; "
            "sweep runs on --ref=%s only.", args.ref,
        )
    log.info("sweep ref = %s (fixed on model side)", args.ref)

    algos = _list_arg(args.algos) or list(ALGOS.keys())
    unknown = [a for a in algos if a not in ALGOS]
    if unknown:
        raise SystemExit(f"unknown algos: {unknown}; known = {list(ALGOS)}")
    ks = _int_list_arg(args.ks) or DEFAULT_KS

    C_model = _load_model_matrix(matrices_path, args.ref)
    coords_model = _load_coords(args.coords_model, id_col="bus")

    rows: list[dict[str, Any]] = []
    for algo in algos:
        for K in ks:
            rows.append(_run_cell(
                ref=args.ref, algo=algo, K=K, C_model=C_model,
                coords_model=coords_model,
                out_dir=out_dir, seed=args.seed, alpha=args.alpha,
            ))

    summary = {
        "run_id": run_id,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "params": {
            "matrices": str(matrices_path),
            "coords_model": str(args.coords_model),
            "ref": args.ref,
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
