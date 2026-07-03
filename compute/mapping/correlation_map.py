"""
CM.1 — correlation map.

Maps each ERCOT SP to its most-correlated model bus over shared hours.

Model and ERCOT sides use different reference-price methods that target
the same conceptual quantity (system marginal energy):
  * model:  `system_lambda_merit_order` (merit-order stack, ~$29 stable)
  * ercot:  `system_lambda` (ERCOT-published system lambda)
Values are expected to track but not equal.

Reads `runs/<run_id>/matrix/congestion_matrices.npz` (produced by
`compute.matrix`) and — in later sections — writes:

  * `runs/<run_id>/mapping/mapping_correlation_<run_id>.parquet`
  * `runs/<run_id>/mapping/mapping_correlation_summary_<run_id>.json`

Usage:
    python -m compute.mapping.correlation_map --run-id v1-120 \
        [--model-ref system_lambda_merit_order] \
        [--ercot-ref system_lambda] \
        [--var-threshold 1.0] [--topk 5] [--dry-run]
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_ROOT = BASE_DIR / "runs"

DEFAULT_MODEL_REF = "system_lambda_merit_order"
DEFAULT_ERCOT_REF = "system_lambda"


def _matrix_npz_path(run_id: str) -> Path:
    return RUNS_ROOT / run_id / "matrix" / "congestion_matrices.npz"


def load_matrices(
    run_id: str,
    model_ref: str = DEFAULT_MODEL_REF,
    ercot_ref: str = DEFAULT_ERCOT_REF,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Load model and ERCOT congestion matrices under (possibly different)
    reference methods and align them on their shared hour axis.

    The model side (`system_lambda_merit_order`) and the ERCOT side
    (`system_lambda`) target the same conceptual reference (system
    marginal energy) but are computed from different sources, so keys
    diverge in the npz.

    Returns (model_C, ercot_C, bus_ids, sp_ids, hours) where matrices are
    (n_bus, n_hours) and (n_sp, n_hours) aligned to the same `hours`.
    """
    path = _matrix_npz_path(run_id)
    if not path.exists():
        raise SystemExit(f"matrix file not found: {path}")

    with np.load(path) as z:
        keys = {
            "model_C": f"{model_ref}_model_C",
            "ercot_C": f"{ercot_ref}_ercot_C",
            "bus_ids": f"{model_ref}_model_bus_ids",
            "sp_ids": f"{ercot_ref}_ercot_sp_ids",
            "model_hours": f"{model_ref}_model_hours",
            "ercot_hours": f"{ercot_ref}_ercot_hours",
        }
        missing = [k for k in keys.values() if k not in z.files]
        if missing:
            raise SystemExit(
                f"missing arrays in {path}: {missing} "
                f"(model_ref={model_ref}, ercot_ref={ercot_ref})"
            )
        model_C = z[keys["model_C"]]
        ercot_C = z[keys["ercot_C"]]
        bus_ids = z[keys["bus_ids"]]
        sp_ids = z[keys["sp_ids"]]
        model_hours = z[keys["model_hours"]]
        ercot_hours = z[keys["ercot_hours"]]

    if model_hours.size == 0 or ercot_hours.size == 0:
        # No shared axis: hand back empty aligned arrays so callers can
        # detect and surface the condition rather than crash on shape.
        hours = np.empty((0,), dtype=str)
        return (
            np.empty((model_C.shape[0], 0), dtype=float),
            np.empty((ercot_C.shape[0], 0), dtype=float),
            bus_ids, sp_ids, hours,
        )

    if np.array_equal(model_hours, ercot_hours):
        return model_C, ercot_C, bus_ids, sp_ids, model_hours

    # Intersect while preserving model-side order.
    ercot_set = {h: i for i, h in enumerate(ercot_hours.tolist())}
    shared: list[str] = []
    m_idx: list[int] = []
    e_idx: list[int] = []
    for i, h in enumerate(model_hours.tolist()):
        j = ercot_set.get(h)
        if j is None:
            continue
        shared.append(h)
        m_idx.append(i)
        e_idx.append(j)
    hours = np.array(shared, dtype=str)
    model_aligned = model_C[:, m_idx] if m_idx else np.empty(
        (model_C.shape[0], 0), dtype=float,
    )
    ercot_aligned = ercot_C[:, e_idx] if e_idx else np.empty(
        (ercot_C.shape[0], 0), dtype=float,
    )
    return model_aligned, ercot_aligned, bus_ids, sp_ids, hours


def prefilter_low_variance(
    C: np.ndarray,
    ids: np.ndarray,
    threshold: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Drop rows whose across-hour std < ``threshold``.

    Returns (C_kept, ids_kept, ids_dropped). Empty input passes through.
    """
    if C.size == 0 or C.shape[1] == 0:
        return C, ids, np.empty((0,), dtype=ids.dtype)
    stds = C.std(axis=1, ddof=0)
    keep = stds >= threshold
    return C[keep], ids[keep], ids[~keep]


def correlate(model_C: np.ndarray, ercot_C: np.ndarray) -> np.ndarray:
    """Pearson correlation matrix R[i, j] = corr(model_i, ercot_j).

    Implemented as a z-scored dot product: R = (A_z @ B_z.T) / n where
    both sides are row-wise mean-centered and unit-variance. Zero-std
    rows (should be filtered upstream) get NaN rows/columns.
    Shape: (n_bus, n_sp).
    """
    if model_C.size == 0 or ercot_C.size == 0:
        return np.empty((model_C.shape[0], ercot_C.shape[0]), dtype=float)
    if model_C.shape[1] != ercot_C.shape[1]:
        raise ValueError(
            f"hour axis mismatch: model_C has {model_C.shape[1]} cols, "
            f"ercot_C has {ercot_C.shape[1]}"
        )
    n = model_C.shape[1]
    a = model_C - model_C.mean(axis=1, keepdims=True)
    b = ercot_C - ercot_C.mean(axis=1, keepdims=True)
    a_std = a.std(axis=1, ddof=0, keepdims=True)
    b_std = b.std(axis=1, ddof=0, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        a_z = np.where(a_std > 0, a / a_std, np.nan)
        b_z = np.where(b_std > 0, b / b_std, np.nan)
    return (a_z @ b_z.T) / n


def select_best_and_topk(
    R: np.ndarray,
    bus_ids: np.ndarray,
    k: int,
) -> tuple[np.ndarray, np.ndarray, list[list[tuple[str, float]]]]:
    """For each SP column, pick the argmax bus and the top-k buses.

    Returns (best_bus, best_corr, topk) where:
      * best_bus[j]  = bus id with max R[:, j]
      * best_corr[j] = that maximum
      * topk[j]      = list of (bus_id, corr) length min(k, n_bus), desc
    NaNs in R are treated as -inf for ranking.
    """
    n_bus, n_sp = R.shape
    k = max(1, min(int(k), n_bus))
    R_ranked = np.where(np.isnan(R), -np.inf, R)

    best_idx = np.argmax(R_ranked, axis=0)
    best_bus = bus_ids[best_idx]
    best_corr = R[best_idx, np.arange(n_sp)]

    # argpartition finds top-k unsorted; then sort within those k for desc order.
    if k < n_bus:
        part = np.argpartition(-R_ranked, kth=k - 1, axis=0)[:k]
    else:
        part = np.tile(np.arange(n_bus)[:, None], (1, n_sp))
    topk: list[list[tuple[str, float]]] = []
    for j in range(n_sp):
        idxs = part[:, j]
        vals = R[idxs, j]
        order = np.argsort(-np.where(np.isnan(vals), -np.inf, vals))
        topk.append([
            (str(bus_ids[idxs[o]]), float(vals[o])) for o in order
        ])
    return best_bus, best_corr, topk


def _smoke_planted_signal(seed: int = 0) -> None:
    """Sanity check that `correlate` + `select_best_and_topk` actually work.

    We fabricate a model matrix of random noise, then build each ERCOT
    SP as `model[i*] + small noise` for a randomly chosen bus i*. If the
    correlation core is correct, argmax_i R[i, j] should return that
    planted i* for every SP j (top-k[0] == planted bus, high corr).

    Fails loudly (assert) if recovery drops below n_sp - 1, catching
    regressions like an axis swap, wrong normalization, or a broken
    top-k sort. Runs offline — no run data required.
    """
    rng = np.random.default_rng(seed)
    n_bus, n_sp, n_hours = 40, 15, 60
    model = rng.standard_normal((n_bus, n_hours))
    planted = rng.integers(0, n_bus, size=n_sp)
    noise = 0.2 * rng.standard_normal((n_sp, n_hours))
    ercot = model[planted] + noise
    R = correlate(model, ercot)
    bus_ids = np.array([f"B{i}" for i in range(n_bus)])
    best_bus, best_corr, topk = select_best_and_topk(R, bus_ids, k=5)
    recovered = sum(
        1 for j in range(n_sp) if best_bus[j] == f"B{planted[j]}"
    )
    print(f"smoke: recovered {recovered}/{n_sp} planted SPs; "
          f"median best_corr={np.median(best_corr):.3f}")
    assert recovered >= n_sp - 1, (
        f"planted-signal recovery failed: {recovered}/{n_sp}"
    )
    assert len(topk[0]) == 5


def _build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Correlate ERCOT SPs to model buses over shared hours.",
    )
    ap.add_argument("--run-id", default=None,
                    help="Run identifier under compute/runs/ "
                         "(required unless --smoke).")
    ap.add_argument("--model-ref", default=DEFAULT_MODEL_REF,
                    help=f"Model-side reference method (default {DEFAULT_MODEL_REF}).")
    ap.add_argument("--ercot-ref", default=DEFAULT_ERCOT_REF,
                    help=f"ERCOT-side reference method (default {DEFAULT_ERCOT_REF}).")
    ap.add_argument("--var-threshold", type=float, default=1.0,
                    help="Drop rows with std < threshold ($/MWh, default 1.0).")
    ap.add_argument("--topk", type=int, default=5,
                    help="Top-k buses to record per SP (default 5).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Load matrices and print shapes, then exit.")
    ap.add_argument("--smoke", action="store_true",
                    help="Run planted-signal smoke check and exit.")
    return ap


def main(argv: list[str] | None = None) -> None:
    args = _build_argparser().parse_args(argv)

    if args.smoke:
        _smoke_planted_signal()
        return

    if not args.run_id:
        raise SystemExit("--run-id is required (unless --smoke)")

    model_C, ercot_C, bus_ids, sp_ids, hours = load_matrices(
        args.run_id, model_ref=args.model_ref, ercot_ref=args.ercot_ref,
    )
    print(f"run_id={args.run_id} model_ref={args.model_ref} "
          f"ercot_ref={args.ercot_ref}")
    print(f"model_C shape={model_C.shape} (bus x hour)")
    print(f"ercot_C shape={ercot_C.shape} (sp x hour)")
    print(f"bus_ids={bus_ids.shape[0]} sp_ids={sp_ids.shape[0]} hours={hours.shape[0]}")

    if args.dry_run:
        return

    # Pipeline: prefilter → correlate → select_best_and_topk → persist (C3).
    model_C, bus_ids, dropped_bus = prefilter_low_variance(
        model_C, bus_ids, args.var_threshold,
    )
    ercot_C, sp_ids, dropped_sp = prefilter_low_variance(
        ercot_C, sp_ids, args.var_threshold,
    )
    print(f"prefilter var>{args.var_threshold}: kept {bus_ids.shape[0]} bus / "
          f"{sp_ids.shape[0]} sp; dropped {dropped_bus.shape[0]} bus / "
          f"{dropped_sp.shape[0]} sp")

    R = correlate(model_C, ercot_C)  # ← bus × sp Pearson correlation matrix
    best_bus, best_corr, topk = select_best_and_topk(R, bus_ids, args.topk)

    finite = best_corr[np.isfinite(best_corr)]
    if finite.size:
        print(f"best_corr: median={np.median(finite):.3f} "
              f"pct>0.7={(finite > 0.7).mean() * 100:.1f}% "
              f"pct>0.5={(finite > 0.5).mean() * 100:.1f}%")

    raise SystemExit("C3 (parquet + summary persistence) not implemented yet")


if __name__ == "__main__":
    main()
