"""
CM.2 — basis regression.

Fits a low-rank temporal basis `f_k(t)` from the model congestion matrix
(via PCA/SVD) and regresses each ERCOT SP series onto that basis:

    ercot_j(t) ≈ Σ_k β_jk · f_k(t) + ε

R² measures how much of each SP the temporal basis explains — the
primary "how well does the model translate to this SP" metric.

Reads `runs/<run_id>/matrix/congestion_matrices.npz` (via
`compute.mapping.correlation_map.load_matrices`) and writes:

  * `runs/<run_id>/mapping/mapping_basis_<run_id>.npz`
    with arrays
      `sp_id, r2, betas`         (per-ERCOT-SP; betas shape `(n_sp, k)`)
      `bus_id, r2_bus, betas_bus`  (per-model-bus; betas_bus shape `(n_bus, k)`)
    Per-bus β-loadings are consumed by the CM.6 clustering runner
    (`hierarchical_on_beta`) as the feature matrix.
  * `runs/<run_id>/mapping/mapping_basis_summary_<run_id>.json`

Usage:
    python -m compute.mapping.basis_regression --run-id v1-120 \
        [--var-target 0.90] [--k K] [--smoke] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from compute.mapping.correlation_map import (
    DEFAULT_ERCOT_REF,
    DEFAULT_MODEL_REF,
    RUNS_ROOT,
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


def regress_all_sps(
    F: np.ndarray,
    ercot_C: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-SP OLS onto temporal basis `F`; return (betas, r2).

    Solves `y_j = α_j + F · β_j + ε` for each SP row `y_j = ercot_C[j, :]`.
    An intercept column is augmented internally so R² is measured against
    the standard SS_tot = Σ(y - mean(y))². The returned `betas` contain
    only the k component coefficients (intercept dropped).

    Shapes: F is (n_hours, k), ercot_C is (n_sp, n_hours).
    Returns betas (n_sp, k) and r2 (n_sp,). Zero-variance SP rows get
    r2 = NaN and zero betas.
    """
    n_sp = int(ercot_C.shape[0])
    k = int(F.shape[1])
    if n_sp == 0 or k == 0 or F.shape[0] == 0:
        return (
            np.zeros((n_sp, k), dtype=float),
            np.full((n_sp,), np.nan, dtype=float),
        )
    if F.shape[0] != ercot_C.shape[1]:
        raise ValueError(
            f"hour axis mismatch: F has {F.shape[0]} rows, "
            f"ercot_C has {ercot_C.shape[1]} cols"
        )

    Y = ercot_C.astype(float, copy=False)
    F_aug = np.concatenate([F, np.ones((F.shape[0], 1), dtype=float)], axis=1)

    # Solve all SPs at once: coeffs is (k+1, n_sp).
    coeffs, *_ = np.linalg.lstsq(F_aug, Y.T, rcond=None)
    betas = coeffs[:k, :].T  # (n_sp, k)

    y_hat = (F_aug @ coeffs).T  # (n_sp, n_hours)
    resid = Y - y_hat
    ss_res = (resid ** 2).sum(axis=1)
    y_centered = Y - Y.mean(axis=1, keepdims=True)
    ss_tot = (y_centered ** 2).sum(axis=1)

    with np.errstate(divide="ignore", invalid="ignore"):
        r2 = np.where(ss_tot > 0, 1.0 - ss_res / ss_tot, np.nan)

    # Zero-variance SPs: zero out betas so downstream consumers don't see
    # arbitrary lstsq output for a degenerate row.
    zero_var = ss_tot <= 0
    if zero_var.any():
        betas[zero_var] = 0.0

    return betas, r2


def _smoke_regress_all_sps(seed: int = 1) -> None:
    """Perfectly-linear synthetic SP recovers R² ≈ 1; zero-variance → NaN."""
    rng = np.random.default_rng(seed)
    n_hours, k = 60, 4
    F = rng.standard_normal((n_hours, k))
    true_betas = rng.standard_normal((3, k))
    intercepts = np.array([1.5, -2.0, 0.0])[:, None]
    y_linear = intercepts + true_betas @ F.T  # (3, n_hours), exact fit
    y_zero = np.full((1, n_hours), 7.0)  # zero variance
    y_noisy = (true_betas[:1] @ F.T) + 0.5 * rng.standard_normal((1, n_hours))
    ercot_C = np.vstack([y_linear, y_zero, y_noisy])

    betas, r2 = regress_all_sps(F, ercot_C)
    print(
        f"smoke regress_all_sps: r2={np.round(r2, 4).tolist()}, "
        f"betas.shape={betas.shape}"
    )
    assert np.all(r2[:3] > 0.999), f"linear rows should be R²≈1, got {r2[:3]}"
    assert np.isnan(r2[3]), f"zero-variance row should be NaN, got {r2[3]}"
    assert np.allclose(betas[3], 0.0)
    assert 0.0 < r2[4] < 1.0, f"noisy row R² out of range: {r2[4]}"
    # Recovered betas should be close to the planted ones for exact rows.
    assert np.allclose(betas[:3], true_betas, atol=1e-8)


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


def _mapping_dir(run_id: str) -> Path:
    return RUNS_ROOT / run_id / "mapping"


def write_outputs(
    run_id: str,
    sp_ids: np.ndarray,
    betas: np.ndarray,
    r2: np.ndarray,
    *,
    bus_ids: np.ndarray,
    betas_bus: np.ndarray,
    r2_bus: np.ndarray,
    k: int,
    cumvar_at_k: float,
    model_ref: str,
    ercot_ref: str,
    var_target: float,
) -> tuple[Path, Path, dict]:
    """Write mapping npz + summary JSON under runs/<run_id>/mapping/.

    Returns (npz_path, summary_path, summary_dict).
    """
    out_dir = _mapping_dir(run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    npz_path = out_dir / f"mapping_basis_{run_id}.npz"
    summary_path = out_dir / f"mapping_basis_summary_{run_id}.json"

    np.savez_compressed(
        npz_path,
        sp_id=sp_ids.astype(str),
        r2=r2.astype(float),
        betas=betas.astype(float),
        bus_id=bus_ids.astype(str),
        r2_bus=r2_bus.astype(float),
        betas_bus=betas_bus.astype(float),
    )

    finite = r2[np.isfinite(r2)]
    n_sp = int(sp_ids.shape[0])
    n_zero_var = int((~np.isfinite(r2)).sum())
    if finite.size:
        r2_median = float(np.median(finite))
        r2_p25 = float(np.percentile(finite, 25))
        r2_p75 = float(np.percentile(finite, 75))
        pct_r2_gt_0_5 = float((finite > 0.5).mean())
        pct_r2_gt_0_7 = float((finite > 0.7).mean())
    else:
        r2_median = r2_p25 = r2_p75 = None
        pct_r2_gt_0_5 = pct_r2_gt_0_7 = None

    finite_bus = r2_bus[np.isfinite(r2_bus)]
    n_bus = int(bus_ids.shape[0])
    n_bus_zero_var = int((~np.isfinite(r2_bus)).sum())
    r2_bus_median = float(np.median(finite_bus)) if finite_bus.size else None

    summary = {
        "run_id": run_id,
        "model_ref": model_ref,
        "ercot_ref": ercot_ref,
        "var_target": float(var_target),
        "k": int(k),
        "cumulative_var": float(cumvar_at_k),
        "n_sp": n_sp,
        "n_sp_zero_var": n_zero_var,
        "r2_median": r2_median,
        "r2_p25": r2_p25,
        "r2_p75": r2_p75,
        "pct_r2_gt_0_5": pct_r2_gt_0_5,
        "pct_r2_gt_0_7": pct_r2_gt_0_7,
        "n_bus": n_bus,
        "n_bus_zero_var": n_bus_zero_var,
        "r2_bus_median": r2_bus_median,
    }
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    return npz_path, summary_path, summary


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
        _smoke_regress_all_sps()
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

    betas, r2 = regress_all_sps(F, ercot_C)
    # Regress model buses onto the same F so hierarchical_on_beta has
    # per-bus features (CM.6). The signature/behavior is identical to
    # regress_all_sps — targets shape is (n_bus, n_hours) here.
    betas_bus, r2_bus = regress_all_sps(F, model_C)

    npz_path, summary_path, summary = write_outputs(
        args.run_id, sp_ids, betas, r2,
        bus_ids=bus_ids, betas_bus=betas_bus, r2_bus=r2_bus,
        k=k, cumvar_at_k=cumvar_at_k,
        model_ref=args.model_ref, ercot_ref=args.ercot_ref,
        var_target=args.var_target,
    )
    print(f"wrote {npz_path} ({npz_path.stat().st_size:,} bytes)")
    print(f"wrote {summary_path}")
    med = summary["r2_median"]
    pct5 = summary["pct_r2_gt_0_5"]
    if med is None:
        print("headline: no finite R²")
    else:
        print(
            f"headline: k={summary['k']}, cumvar={summary['cumulative_var']:.3f}, "
            f"median R²={med:.3f}, %R²>0.5={pct5*100:.1f}% "
            f"(n_sp={summary['n_sp']}, zero_var={summary['n_sp_zero_var']})"
        )


if __name__ == "__main__":
    main()
