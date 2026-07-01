import logging
import numpy as np
import pandas as pd
import pypsa

logger = logging.getLogger(__name__)

# Sign convention for μ_signed = mu_lower − mu_upper.
# Verified against DFW 2025-08-19T19:00 by compute/verify_sign_convention.py:
# import-side buses in north_central weather zone must carry positive
# modeled_congestion when a north-central-importing line binds. If that
# verification fails after a network change, flip this constant (do not fudge
# the metric) and rerun the script.
MU_SIGN = +1.0  # μ_signed = MU_SIGN * (mu_lower - mu_upper)

# Threshold below which a bus is considered not to influence a branch. Used to
# gate the max aggregation in binding_proximity_at so trivially-small PTDF
# entries don't drag a bus's proximity toward a saturated line it barely drives.
PTDF_INFLUENCE_EPS = 1e-4


def modeled_congestion_at(
    n: pypsa.Network,
    line_mu_upper: pd.Series | None,
    line_mu_lower: pd.Series | None,
    tx_mu_upper: pd.Series | None,
    tx_mu_lower: pd.Series | None,
    ptdf_full: np.ndarray,
    sub_buses: list,
) -> pd.Series:
    """Signed modeled congestion per bus at a single snapshot.

    modeled_congestion[b] = Σ_ℓ PTDF[ℓ, b] · μ_signed_ℓ    ($/MWh, signed)
    μ_signed_ℓ = MU_SIGN · (mu_lower_ℓ − mu_upper_ℓ)

    Series args are 1-D per-branch slices (e.g. n.lines_t.mu_upper.loc[ts]).
    Pass None if duals are absent at this snapshot. PTDF rows are ordered
    [lines, transformers]; columns are sub_buses.
    """
    mu_line = _signed_mu(n.lines.index, line_mu_upper, line_mu_lower)
    mu_tx   = _signed_mu(n.transformers.index, tx_mu_upper, tx_mu_lower)
    mu_full = np.concatenate([mu_line, mu_tx])

    mc_vec = ptdf_full.T @ mu_full  # (n_bus,)
    return pd.Series(mc_vec, index=sub_buses, name='modeled_congestion')


def binding_proximity_at(
    n: pypsa.Network,
    line_p0: pd.Series | None,
    tx_p0: pd.Series | None,
    line_s_max_pu: pd.Series | None,
    tx_s_max_pu: pd.Series | None,
    ptdf_full: np.ndarray,
    sub_buses: list,
) -> pd.Series:
    """Loading-based binding proximity per bus at a single snapshot.

    binding_proximity[b] = max_{ℓ : |PTDF[ℓ, b]| > PTDF_INFLUENCE_EPS}
                              |PTDF[ℓ, b]| · |flow_ℓ| / (s_nom_opt_ℓ · s_max_pu_ℓ)

    NaN for buses that do not meaningfully influence any branch. Uses
    s_nom_opt with s_nom fallback; s_max_pu takes the time-varying slice
    when provided, else the static column, else 1.0.
    """
    prox_line = _prox_branch(n.lines,        line_p0, line_s_max_pu)
    prox_tx   = _prox_branch(n.transformers, tx_p0,   tx_s_max_pu)
    prox_full = np.concatenate([prox_line, prox_tx])  # (n_branches,)

    ptdf_abs = np.abs(ptdf_full)                       # (n_branches, n_bus)
    weighted = ptdf_abs * prox_full[:, np.newaxis]     # (n_branches, n_bus)
    influence = ptdf_abs > PTDF_INFLUENCE_EPS          # (n_branches, n_bus)

    weighted_masked = np.where(influence, weighted, -np.inf)
    bp_vec = weighted_masked.max(axis=0)
    bp_vec = np.where(np.isfinite(bp_vec), bp_vec, np.nan)

    return pd.Series(bp_vec, index=sub_buses, name='binding_proximity')


def _signed_mu(
    idx: pd.Index,
    mu_upper: pd.Series | None,
    mu_lower: pd.Series | None,
) -> np.ndarray:
    """μ_signed aligned to idx (fills zeros for missing duals). Preserves sign."""
    n = len(idx)
    mu_up = (mu_upper.reindex(idx).fillna(0).values
             if mu_upper is not None else np.zeros(n))
    mu_lo = (mu_lower.reindex(idx).fillna(0).values
             if mu_lower is not None else np.zeros(n))
    return MU_SIGN * (mu_lo - mu_up)


def _prox_branch(
    component: pd.DataFrame,
    p0: pd.Series | None,
    s_max_pu_slice: pd.Series | None,
) -> np.ndarray:
    """Per-branch proximity = |flow| / (s_nom_opt · s_max_pu)."""
    idx = component.index
    n = len(idx)

    flow = (p0.abs().reindex(idx).fillna(0).values
            if p0 is not None else np.zeros(n))

    s_nom = (component['s_nom_opt'].values
             if 's_nom_opt' in component.columns
             else component['s_nom'].values)

    if s_max_pu_slice is not None:
        s_max_pu = (s_max_pu_slice.reindex(idx)
                    .fillna(component['s_max_pu']).fillna(1.0).values)
    else:
        s_max_pu = component['s_max_pu'].reindex(idx).fillna(1.0).values

    limit = np.maximum(s_nom * s_max_pu, 1.0)  # 1 MW floor to avoid /0
    return flow / limit


def modeled_congestion_diagnostics(mc: pd.Series) -> None:
    print(f"\nmodeled_congestion stats (signed, $/MWh):")
    print(mc.describe())

    abs_mc = mc.abs()
    total_abs = float(abs_mc.sum())
    n_pos = int((mc > 0).sum())
    n_neg = int((mc < 0).sum())
    sum_pos = float(mc[mc > 0].sum())
    sum_neg = float(mc[mc < 0].sum())
    print(f"Signs: {n_pos} positive, {n_neg} negative")
    print(f"Σ positive={sum_pos:.2f}, Σ negative={sum_neg:.2f}")
    if total_abs > 0:
        top10 = mc.reindex(abs_mc.nlargest(10).index)
        print(f"Top 10 by |modeled_congestion| (signed):")
        print(top10.round(3).to_string())
        print(f"Top 10 |value| share: {abs_mc.nlargest(10).sum() / total_abs:.1%}")


def binding_proximity_diagnostics(bp: pd.Series) -> None:
    print(f"\nbinding_proximity stats (loading fraction):")
    print(bp.describe())
    print(f"Buses > 0.9: {int((bp > 0.9).sum())}")
    print(f"Buses > 1.0 (should be ~0, solver tolerance): "
          f"{int((bp > 1.0).sum())}")
    print(f"Top 10 buses by proximity:")
    print(bp.nlargest(10).round(3).to_string())
