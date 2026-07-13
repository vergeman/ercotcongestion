"""
KKT reconstruction of system λ from existing PyPSA solve outputs.

For each bus i, the DC OPF LMP decomposition gives:
  LMP_i = λ̂ + Σ_b PTDF[b, i] × (μ_upper_b − μ_lower_b)

So λ̂ = LMP_i − Σ_b PTDF[b, i] × (μ_upper_b − μ_lower_b), which should be
bus-independent at the optimum. Disagreement across buses = residual.

PTDF row order is [lines, transformers] per ptdf_lodf.py.
"""
import numpy as np
import pandas as pd


def reconstruct_lambda(
    lmps: pd.Series,
    line_mu_upper: pd.Series | None,
    line_mu_lower: pd.Series | None,
    tx_mu_upper:   pd.Series | None,
    tx_mu_lower:   pd.Series | None,
    ptdf: np.ndarray,
    bus_names: list[str],
    line_names: list[str],
    tx_names:   list[str] | None = None,
) -> dict:
    """Single-snapshot λ̂ reconstruction. All Series are 1-D slices for one
    timestamp. Missing duals (None) treated as zero.

    Returns dict with:
      lambda_hat            float — mean across buses
      lambda_hat_per_bus    pd.Series — per-bus λ̂_i, before averaging
      residual_norm         float — ||λ̂_i − mean||_2
      residual_max          float — max abs deviation
      residual_p50          float — median abs deviation
      residual_p95          float — 95th-percentile abs deviation
      congestion_per_bus    pd.Series — Σ PTDF × (μ_up − μ_lo), useful for debug
    """
    lmps_arr = lmps.reindex(bus_names).astype(float).values

    line_shadow = _signed_shadow(line_mu_upper, line_mu_lower, line_names)
    branch_shadow = line_shadow
    if tx_names is not None:
        tx_shadow = _signed_shadow(tx_mu_upper, tx_mu_lower, tx_names)
        branch_shadow = np.concatenate([line_shadow, tx_shadow])

    # PTDF shape: (n_branches, n_buses). Congestion contribution per bus:
    # c_i = Σ_b PTDF[b, i] × shadow_b
    congestion_per_bus = ptdf.T @ branch_shadow

    lambda_hat_per_bus = lmps_arr - congestion_per_bus
    lambda_hat = float(np.mean(lambda_hat_per_bus))
    resid = lambda_hat_per_bus - lambda_hat

    return {
        'lambda_hat':         lambda_hat,
        'lambda_hat_per_bus': pd.Series(lambda_hat_per_bus, index=bus_names),
        'residual_norm':      float(np.linalg.norm(resid)),
        'residual_max':       float(np.max(np.abs(resid))),
        'residual_p50':       float(np.median(np.abs(resid))),
        'residual_p95':       float(np.quantile(np.abs(resid), 0.95)),
        'congestion_per_bus': pd.Series(congestion_per_bus, index=bus_names),
    }


def _signed_shadow(
    mu_upper: pd.Series | None,
    mu_lower: pd.Series | None,
    names: list[str],
) -> np.ndarray:
    """(μ_upper − μ_lower) aligned to `names`, NaN/missing → 0."""
    up = (mu_upper.reindex(names).fillna(0.0).values
          if mu_upper is not None else np.zeros(len(names)))
    lo = (mu_lower.reindex(names).fillna(0.0).values
          if mu_lower is not None else np.zeros(len(names)))
    return up - lo
