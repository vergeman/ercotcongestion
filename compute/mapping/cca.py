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
import json
from pathlib import Path

import numpy as np

from compute.mapping.correlation_map import (
    DEFAULT_ERCOT_REF,
    DEFAULT_MODEL_REF,
    RUNS_ROOT,
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


def _top_temporal_pcs(C: np.ndarray, k: int) -> np.ndarray:
    """Top-k temporal PCs (left singular vectors) of `C` as (n_hours, k').

    `k'` = min(k, rank) — may be smaller than `k` if the matrix is
    rank-deficient. Returns an empty (0, 0) array if `C` is empty.
    """
    if C.size == 0 or C.shape[1] == 0:
        return np.empty((0, 0), dtype=float)
    X = C.T.astype(float, copy=False)
    X = X - X.mean(axis=0, keepdims=True)
    U, _, _ = np.linalg.svd(X, full_matrices=False)
    kk = max(0, min(int(k), U.shape[1]))
    return U[:, :kk]


def _pearson_matrix(A: np.ndarray, B: np.ndarray) -> np.ndarray:
    """Pearson correlation matrix R[i, j] = corr(A[:, i], B[:, j]).

    Handles zero-variance columns by returning NaN for the affected
    row/column entries. Assumes A and B share the same first axis.
    """
    if A.size == 0 or B.size == 0:
        return np.empty((A.shape[1], B.shape[1]), dtype=float)
    a = A - A.mean(axis=0, keepdims=True)
    b = B - B.mean(axis=0, keepdims=True)
    a_std = a.std(axis=0, ddof=0, keepdims=True)
    b_std = b.std(axis=0, ddof=0, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        a_z = np.where(a_std > 0, a / a_std, np.nan)
        b_z = np.where(b_std > 0, b / b_std, np.nan)
    n = A.shape[0]
    return (a_z.T @ b_z) / n


def _best_match_perm(M_abs: np.ndarray) -> list[tuple[int, int, float]]:
    """Greedy best-match matching on |correlation| matrix.

    Repeatedly picks the largest available |corr| cell, then masks its
    row and column. Returns a list of `(model_pc, ercot_pc, |corr|)`
    tuples in match order (highest first). For small k (≤5) this is
    equivalent to Hungarian; we avoid a scipy dep.
    """
    if M_abs.size == 0:
        return []
    M = np.where(np.isnan(M_abs), -1.0, M_abs).copy()
    n_rows, n_cols = M.shape
    n = min(n_rows, n_cols)
    matches: list[tuple[int, int, float]] = []
    for _ in range(n):
        flat_idx = int(np.argmax(M))
        i, j = divmod(flat_idx, n_cols)
        val = float(M[i, j])
        if val < 0:
            break
        matches.append((i, j, val))
        M[i, :] = -1.0
        M[:, j] = -1.0
    return matches


def pc_cross_corr(
    model_C: np.ndarray, ercot_C: np.ndarray, k: int = 5,
) -> tuple[np.ndarray, np.ndarray, list[tuple[int, int, float]]]:
    """Pairwise Pearson correlation between top-k temporal PCs of each side.

    Returns:
      * matrix (k' × k') of signed Pearson correlations, where k' is
        min(k, ranks of the two matrices);
      * diag: same-index correlations (matrix[i, i]);
      * best_match_perm: greedy matching on |correlation| — pairs each
        model PC to a distinct ERCOT PC by strongest absolute agreement.
        Necessary because SVD component ordering can permute across
        independent decompositions (and signs are arbitrary).
    """
    U_m = _top_temporal_pcs(model_C, k)
    U_e = _top_temporal_pcs(ercot_C, k)
    if U_m.shape[1] == 0 or U_e.shape[1] == 0:
        return np.empty((0, 0), dtype=float), np.empty((0,), dtype=float), []

    kk = min(U_m.shape[1], U_e.shape[1])
    U_m = U_m[:, :kk]
    U_e = U_e[:, :kk]
    M = _pearson_matrix(U_m, U_e)  # (kk, kk)
    diag = np.array([M[i, i] for i in range(kk)], dtype=float)
    best = _best_match_perm(np.abs(M))
    return M, diag, best


def _smoke_pc_cross_corr(seed: int = 0) -> None:
    """Two matrices sharing top-3 temporal PCs should recover them ≈1.

    Uses column-orthonormal loading matrices A_m, A_e (via QR) so that
    each side's temporal SVD-U columns land on the *same* directions as
    Z's rows (up to sign) — otherwise random A mixes shared structure
    across PCs and best-match |corr| falls to ~0.85. Best-match is
    used rather than diag because signs and orderings can permute.
    """
    rng = np.random.default_rng(seed)
    n_hours, n_bus, n_sp = 80, 40, 25
    Z = rng.standard_normal((3, n_hours))
    A_m, _ = np.linalg.qr(rng.standard_normal((n_bus, 3)))
    A_e, _ = np.linalg.qr(rng.standard_normal((n_sp, 3)))
    model_C = A_m @ Z + 0.02 * rng.standard_normal((n_bus, n_hours))
    ercot_C = A_e @ Z + 0.02 * rng.standard_normal((n_sp, n_hours))
    M, diag, best = pc_cross_corr(model_C, ercot_C, k=3)
    matched = sorted([abs(v) for _, _, v in best], reverse=True)
    print(f"smoke pc_cross_corr: best-match |corr|={[round(v, 4) for _, _, v in best]}, "
          f"diag={np.round(diag, 4).tolist()}")
    assert all(v > 0.99 for v in matched), (
        f"all 3 shared PCs should best-match ≈1, got {matched}"
    )


def _mapping_dir(run_id: str) -> Path:
    return RUNS_ROOT / run_id / "mapping"


def write_outputs(
    run_id: str,
    canonical_correlations: np.ndarray,
    cca_info: dict,
    pc_matrix: np.ndarray,
    pc_diag: np.ndarray,
    pc_best: list[tuple[int, int, float]],
    *,
    model_ref: str,
    ercot_ref: str,
    var_target: float,
    n_components: int,
    pc_k: int,
) -> tuple[Path, dict]:
    """Write mapping_cca_<run_id>.json under runs/<run_id>/mapping/.

    Returns (json_path, payload).
    """
    out_dir = _mapping_dir(run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"mapping_cca_{run_id}.json"

    def _clean(x: float) -> float | None:
        return float(x) if np.isfinite(x) else None

    payload = {
        "run_id": run_id,
        "model_ref": model_ref,
        "ercot_ref": ercot_ref,
        "var_target": float(var_target),
        "n_components_requested": int(n_components),
        "n_components": int(cca_info.get("n_components", 0)),
        "r_model": int(cca_info.get("r_model", 0)),
        "r_ercot": int(cca_info.get("r_ercot", 0)),
        "cumvar_model": _clean(cca_info.get("cumvar_model", float("nan"))),
        "cumvar_ercot": _clean(cca_info.get("cumvar_ercot", float("nan"))),
        "canonical_correlations": [
            _clean(v) for v in canonical_correlations.tolist()
        ],
        "pc_k": int(pc_k),
        "pc_cross_corr": [
            [_clean(v) for v in row] for row in pc_matrix.tolist()
        ],
        "pc_diag": [_clean(v) for v in pc_diag.tolist()],
        "pc_best_match": [
            {"model_pc": int(i), "ercot_pc": int(j), "abs_corr": _clean(v)}
            for (i, j, v) in pc_best
        ],
    }
    with open(json_path, "w") as f:
        json.dump(payload, f, indent=2)
    return json_path, payload


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
    ap.add_argument("--pc-k", type=int, default=5,
                    help="Top-k temporal PCs for the cross-check (default 5).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Load, fit CCA, print top corrs; skip writes.")
    ap.add_argument("--smoke", action="store_true",
                    help="Run offline smoke checks and exit.")
    return ap


def main(argv: list[str] | None = None) -> None:
    args = _build_argparser().parse_args(argv)

    if args.smoke:
        _smoke_fit_cca()
        _smoke_pc_cross_corr()
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

    pc_matrix, pc_diag, pc_best = pc_cross_corr(model_C, ercot_C, k=args.pc_k)

    if args.dry_run:
        return

    json_path, payload = write_outputs(
        args.run_id, corrs, info, pc_matrix, pc_diag, pc_best,
        model_ref=args.model_ref, ercot_ref=args.ercot_ref,
        var_target=args.var_target,
        n_components=args.n_components, pc_k=args.pc_k,
    )
    print(f"wrote {json_path}")
    top_c = payload["canonical_correlations"][0] if payload["canonical_correlations"] else None
    top_pc = payload["pc_best_match"][0] if payload["pc_best_match"] else None
    if top_c is None:
        print("headline: no canonical correlations (rank-deficient input)")
    else:
        pc_str = (
            f"PC best-match: model{top_pc['model_pc']}↔ercot{top_pc['ercot_pc']} "
            f"|r|={top_pc['abs_corr']:.3f}"
            if top_pc else "PC best-match: n/a"
        )
        print(f"headline: top canonical corr={top_c:.3f}; {pc_str}")


if __name__ == "__main__":
    main()
