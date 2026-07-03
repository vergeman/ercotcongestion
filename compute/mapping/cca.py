"""
CM.3 — CCA scalar.

Reports a single system-level "shared structure" scalar between the model
congestion matrix and the ERCOT congestion matrix, complementing the
SP-level metrics in [[correlation_map]] and [[basis_regression]].

We use canonical correlation analysis (CCA) between `model_C.T` and
`ercot_C.T` — hours as samples, buses/SPs as features. Since n_features
(~2700 buses, ~900 SPs) far exceeds n_samples (~100 hours), the raw
sample covariance matrices are singular; we regularize via SVD-based
truncation of each side to its top-r PCA subspace before computing the
cross-correlation SVD.

Reads `runs/<run_id>/matrix/congestion_matrices.npz` (via
`compute.mapping.correlation_map.load_matrices`) and writes:

  * `runs/<run_id>/mapping/mapping_cca_<run_id>.json`

Usage:
    python -m compute.mapping.cca --run-id v1-120 \
        [--n-components 5] [--var-target 0.90] [--smoke] [--dry-run]
"""
from __future__ import annotations

import argparse

import numpy as np

from compute.mapping.correlation_map import (
    DEFAULT_ERCOT_REF,
    DEFAULT_MODEL_REF,
    load_matrices,
)


def _orthonormal_basis(
    C: np.ndarray, var_target: float
) -> tuple[np.ndarray, int, float]:
    """Return (Q, r, cumvar_at_r) where Q is a (n_hours, r) orthonormal
    basis of the top-r temporal PCA subspace of `C`.

    Input `C` is (n_features, n_hours). We treat hours as samples, features
    as columns → center per-feature, SVD, and keep the top-r *left*
    singular vectors (U[:, :r]) — these are unit-length in hour-space and
    directly comparable across model/ERCOT (unlike right singular vectors,
    which live in bus/SP-space).
    """
    if C.size == 0 or C.shape[1] == 0:
        return np.empty((0, 0), dtype=float), 0, 0.0

    X = C.T.astype(float, copy=False)  # (n_hours, n_features)
    X = X - X.mean(axis=0, keepdims=True)

    U, S, _ = np.linalg.svd(X, full_matrices=False)
    n_samples = X.shape[0]
    eigenvalues = (S ** 2) / max(n_samples - 1, 1)
    total_var = float(eigenvalues.sum())
    if total_var <= 0:
        return np.empty((n_samples, 0), dtype=float), 0, 0.0
    cumvar = np.cumsum(eigenvalues / total_var)
    r = int(np.searchsorted(cumvar, var_target, side="left")) + 1
    r = max(1, min(r, S.shape[0]))
    return U[:, :r], r, float(cumvar[r - 1])


def fit_cca(
    model_C: np.ndarray,
    ercot_C: np.ndarray,
    n_components: int = 5,
    var_target: float = 0.90,
) -> tuple[np.ndarray, dict]:
    """Compute top canonical correlations between model and ERCOT.

    Both matrices are shape (n_features, n_hours). Each side is truncated
    to its top-r_x / top-r_y temporal PCA subspace (cumulative variance
    ≥ `var_target`); canonical correlations are the singular values of
    the r_x × r_y cross-projection matrix.

    Returns `(canonical_correlations, info)` where the length of the
    array is `min(n_components, r_x, r_y)`. `info` records the truncation
    ranks and cumulative variance used.
    """
    Q_m, r_m, cum_m = _orthonormal_basis(model_C, var_target)
    Q_e, r_e, cum_e = _orthonormal_basis(ercot_C, var_target)
    max_c = min(int(n_components), r_m, r_e)
    if max_c <= 0:
        return (
            np.empty((0,), dtype=float),
            {
                "r_model": r_m, "r_ercot": r_e,
                "cumvar_model": cum_m, "cumvar_ercot": cum_e,
                "n_components": 0,
            },
        )

    M = Q_m.T @ Q_e  # (r_m, r_e)
    sigma = np.linalg.svd(M, compute_uv=False)
    # Numerical: cap to [0, 1] — orthonormal Q's guarantee this analytically.
    sigma = np.clip(sigma[:max_c], 0.0, 1.0)
    info = {
        "r_model": r_m, "r_ercot": r_e,
        "cumvar_model": cum_m, "cumvar_ercot": cum_e,
        "n_components": int(max_c),
    }
    return sigma, info


def _smoke_fit_cca(seed: int = 0) -> None:
    """Two matrices with a shared latent factor → top canonical corr ≈ 1.

    Construct model_C, ercot_C = A @ Z + noise for a shared Z (rank-2
    signal in hour-space), with independent A_m, A_e. The top canonical
    correlation should be near 1 since both sides share the same
    temporal latent Z; the second should be lower.
    """
    rng = np.random.default_rng(seed)
    n_hours, n_bus, n_sp, r_shared = 80, 50, 30, 2
    Z = rng.standard_normal((r_shared, n_hours))  # shared temporal signal
    A_m = rng.standard_normal((n_bus, r_shared))
    A_e = rng.standard_normal((n_sp, r_shared))
    model_C = A_m @ Z + 0.05 * rng.standard_normal((n_bus, n_hours))
    ercot_C = A_e @ Z + 0.05 * rng.standard_normal((n_sp, n_hours))

    corrs, info = fit_cca(model_C, ercot_C, n_components=5, var_target=0.95)
    print(f"smoke fit_cca: canonical_correlations={np.round(corrs, 4).tolist()}, "
          f"info={info}")
    assert corrs.shape[0] >= 1
    assert corrs[0] > 0.99, f"expected top canonical corr ≈ 1, got {corrs[0]}"

    # Independent-signal control: top canonical correlation should NOT be 1.
    Z_e = rng.standard_normal((r_shared, n_hours))
    ercot_indep = A_e @ Z_e + 0.05 * rng.standard_normal((n_sp, n_hours))
    corrs2, _ = fit_cca(model_C, ercot_indep, n_components=5, var_target=0.95)
    print(f"smoke fit_cca (independent): top={corrs2[0]:.4f}")
    # With truncation at var=0.95 and independent signals, we still get
    # some correlation from the noise/finite-sample overlap — but the
    # shared-signal case should be strictly higher.
    assert corrs[0] > corrs2[0], (
        f"shared should exceed independent: {corrs[0]} vs {corrs2[0]}"
    )


def _build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="CCA between model and ERCOT congestion matrices.",
    )
    ap.add_argument("--run-id", default=None,
                    help="Run identifier under compute/runs/ "
                         "(required unless --smoke).")
    ap.add_argument("--model-ref", default=DEFAULT_MODEL_REF,
                    help=f"Model-side reference method (default {DEFAULT_MODEL_REF}).")
    ap.add_argument("--ercot-ref", default=DEFAULT_ERCOT_REF,
                    help=f"ERCOT-side reference method (default {DEFAULT_ERCOT_REF}).")
    ap.add_argument("--n-components", type=int, default=5,
                    help="Top-N canonical correlations to report (default 5).")
    ap.add_argument("--var-target", type=float, default=0.90,
                    help="Cumulative variance target for per-side truncation.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Load, fit CCA, print top corrs; skip writes.")
    ap.add_argument("--smoke", action="store_true",
                    help="Run offline smoke checks and exit.")
    return ap


def main(argv: list[str] | None = None) -> None:
    args = _build_argparser().parse_args(argv)

    if args.smoke:
        _smoke_fit_cca()
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

    corrs, info = fit_cca(
        model_C, ercot_C,
        n_components=args.n_components, var_target=args.var_target,
    )
    print(f"cca: canonical_correlations={np.round(corrs, 4).tolist()}")
    print(f"     r_model={info['r_model']} (cumvar={info['cumvar_model']:.3f}) "
          f"r_ercot={info['r_ercot']} (cumvar={info['cumvar_ercot']:.3f})")


if __name__ == "__main__":
    main()
