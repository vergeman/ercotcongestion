"""
CM.2 — basis regression.

Fits a low-rank temporal basis `f_k(t)` from the model congestion matrix
(via PCA/SVD) and regresses each ERCOT SP series onto that basis:

    ercot_j(t) ≈ Σ_k β_jk · f_k(t) + ε

R² measures how much of each SP the temporal basis explains — the
primary "how well does the model translate to this SP" metric.

Reads `runs/<run_id>/matrix/congestion_matrices.npz` (via
`compute.mapping.correlation_map.load_matrices`) and writes:

  * `runs/<run_id>/mapping/mapping_basis_<run_id>.parquet`
    with columns `sp_id, r2, betas` (betas is a list column of length k).
  * `runs/<run_id>/mapping/mapping_basis_summary_<run_id>.json`

Usage:
    python -m compute.mapping.basis_regression --run-id v1-120 \
        [--var-target 0.90] [--k K] [--smoke] [--dry-run]
"""
from __future__ import annotations

import argparse

import numpy as np

from compute.mapping.correlation_map import (
    DEFAULT_ERCOT_REF,
    DEFAULT_MODEL_REF,
    load_matrices,
)


def fit_components(
    model_C: np.ndarray,
    var_target: float = 0.90,
    k_override: int | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """PCA on the model congestion matrix; return temporal components.

    Input `model_C` is (n_bus, n_hours). Samples are hours, features are
    buses — we center per-bus (mean across time removed for each bus),
    matching `compute.congestion.pca_variance_explained`'s convention.

    Returns (F, singular_values, cumvar, k) where:
      * F is (n_hours, k), each column a temporal component f_k(t)
        given by `U[:, k] * S[k]`.
      * singular_values is the full 1-D array of singular values.
      * cumvar is the cumulative explained-variance fraction (full length).
      * k is the number of components chosen (min such that
        cumvar[k-1] >= var_target, or `k_override` if provided).
    """
    if model_C.ndim != 2 or model_C.size == 0 or model_C.shape[1] == 0:
        return (
            np.empty((0, 0), dtype=float),
            np.empty((0,), dtype=float),
            np.empty((0,), dtype=float),
            0,
        )

    # Samples = hours (rows), features = buses (cols). Center per-bus.
    X = model_C.T.astype(float, copy=False)
    X = X - X.mean(axis=0, keepdims=True)

    U, S, _ = np.linalg.svd(X, full_matrices=False)
    n_samples = X.shape[0]
    eigenvalues = (S ** 2) / max(n_samples - 1, 1)
    total_var = float(eigenvalues.sum())
    if total_var <= 0:
        cumvar = np.zeros_like(eigenvalues)
    else:
        cumvar = np.cumsum(eigenvalues / total_var)

    if k_override is not None:
        k = int(k_override)
    else:
        # smallest k such that cumvar[k-1] >= var_target
        idx = np.searchsorted(cumvar, var_target, side="left")
        k = int(idx) + 1
    k = max(1, min(k, S.shape[0]))

    F = U[:, :k] * S[:k]
    return F, S, cumvar, k


def _smoke_fit_components(seed: int = 0) -> None:
    """Rank-3 synthetic matrix: `k` should converge to 3 at var_target=0.99.

    We construct model_C = A @ B where A is (n_bus, 3) and B is (3, n_hours),
    both random. The centered matrix is at most rank-3 (rank-2 if the row
    means happen to sit exactly in the row span, but generically rank-3),
    so PCA should hit ≥0.99 cumulative variance at k=3.
    """
    rng = np.random.default_rng(seed)
    n_bus, n_hours = 50, 80
    A = rng.standard_normal((n_bus, 3))
    B = rng.standard_normal((3, n_hours))
    model_C = A @ B + 0.001 * rng.standard_normal((n_bus, n_hours))
    F, S, cumvar, k = fit_components(model_C, var_target=0.99)
    print(
        f"smoke fit_components: k={k}, cumvar@k={cumvar[k-1]:.4f}, "
        f"F.shape={F.shape}"
    )
    assert k == 3, f"expected k=3 for rank-3 matrix, got k={k}"
    assert F.shape == (n_hours, 3)
    assert cumvar[2] >= 0.99


def _build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Basis regression: PCA temporal components + per-SP OLS.",
    )
    ap.add_argument("--run-id", default=None,
                    help="Run identifier under compute/runs/ "
                         "(required unless --smoke).")
    ap.add_argument("--model-ref", default=DEFAULT_MODEL_REF,
                    help=f"Model-side reference method (default {DEFAULT_MODEL_REF}).")
    ap.add_argument("--ercot-ref", default=DEFAULT_ERCOT_REF,
                    help=f"ERCOT-side reference method (default {DEFAULT_ERCOT_REF}).")
    ap.add_argument("--var-target", type=float, default=0.90,
                    help="Cumulative explained-variance target for k selection.")
    ap.add_argument("--k", type=int, default=None,
                    help="Override k (number of PCA components).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Load matrices, fit components, print k; then exit.")
    ap.add_argument("--smoke", action="store_true",
                    help="Run offline smoke checks and exit.")
    return ap


def main(argv: list[str] | None = None) -> None:
    args = _build_argparser().parse_args(argv)

    if args.smoke:
        _smoke_fit_components()
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

    F, S, cumvar, k = fit_components(
        model_C, var_target=args.var_target, k_override=args.k,
    )
    cumvar_at_k = float(cumvar[k - 1]) if k > 0 else 0.0
    print(f"components: k={k}, cumvar@k={cumvar_at_k:.4f}, "
          f"F shape={F.shape}")

    if args.dry_run:
        return


if __name__ == "__main__":
    main()
