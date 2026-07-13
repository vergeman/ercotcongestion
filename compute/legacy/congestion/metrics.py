import logging
from datetime import datetime

import numpy as np
import pandas as pd
import pypsa

from compute.legacy.ptdf_lodf import distribute_slack

from .compute import CUSTOM_HUBS, HUB_BUSAVG

logger = logging.getLogger(__name__)

# Number of nearest buses averaged into each hub LMP. ERCOT's HB_BUSAVG SPP
# is the mean over all buses tagged to a hub — a single-nearest lookup (k=1)
# is one arbitrary sample from that group. The 0049 S4.2 sweep
# (docs/hub_k_sweep.md) walked k ∈ {1, 5, 25, 100, 200, 300, 500, 1000, 2000}
# against the ERCOT DAM SPP over the v1-120-postfix window and found a
# U-shape: k=1 and k=200 tie on median-ratio drift (0.23 averaged across
# hubs) and HB_WEST negative incidence (48/93), but k=200 additionally
# improves correlations at every hub and drops HB_NORTH's max spike 39%
# ($412 → $252). Above k=300 the hubs collapse into a system-wide mean and
# HB_WEST swings positive. Kept as a parameter so the sweep can rerun
# cheaply after the full-year re-backfill.
HUB_K_NEAREST = 200

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
#
# binding_proximity_at uses a load-weighted DISTRIBUTED-slack PTDF (see
# _load_weighted_slack and ptdf_lodf.distribute_slack). modeled_congestion_at
# stays on the single-slack PTDF: its μ-weighted sum is a linear combination
# of PTDF rows whose μ is ~0 on the radial slack-side transformer, so the
# Texas2k slack artifact does not propagate into Σ PTDF · μ. Changing that
# path would perturb the sign-convention verification (verify_sign_convention.py)
# validated at DFW 2025-08-19T19:00 for zero benefit.
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
    slack_weights: np.ndarray | None = None,
) -> pd.Series:
    """Loading-based binding proximity per bus at a single snapshot.

    binding_proximity[b] = max_{ℓ : |PTDF[ℓ, b]| > PTDF_INFLUENCE_EPS}
                              |PTDF[ℓ, b]| · |flow_ℓ| / (s_nom_opt_ℓ · s_max_pu_ℓ)

    NaN for buses that do not meaningfully influence any branch. Uses
    s_nom_opt with s_nom fallback; s_max_pu takes the time-varying slice
    when provided, else the static column, else 1.0.

    When `slack_weights` is provided (length must equal `ptdf_full.shape[1]`
    and sum to 1), PTDF is first converted to a distributed-slack PTDF via
    `distribute_slack`. Without weights, uses `ptdf_full` unchanged — the
    single-slack behavior — for backward compatibility with callers that
    have not yet been updated.
    """
    if slack_weights is not None:
        ptdf_used = distribute_slack(ptdf_full, slack_weights)
    else:
        ptdf_used = ptdf_full

    prox_line = _prox_branch(n.lines,        line_p0, line_s_max_pu)
    prox_tx   = _prox_branch(n.transformers, tx_p0,   tx_s_max_pu)
    prox_full = np.concatenate([prox_line, prox_tx])  # (n_branches,)

    ptdf_abs = np.abs(ptdf_used)                       # (n_branches, n_bus)
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


def build_hub_lmps(
    lmps: pd.Series,
    n: pypsa.Network,
    hub_centroids: pd.DataFrame,
    k: int = HUB_K_NEAREST,
) -> dict[str, float]:
    """Map each ERCOT hub centroid to the mean LMP of its k nearest synthetic
    buses. k=1 is the original single-nearest behaviour and reproduces
    unmodified pre-0049 outputs. Larger k damps single-bus outliers (see
    module-level `HUB_K_NEAREST`)."""
    valid = lmps.dropna()

    bus_xy = n.buses.loc[valid.index, ['y', 'x']].rename(
        columns={'y': 'lat', 'x': 'lon'}
    ).dropna()
    bus_coords = bus_xy[['lat', 'lon']].to_numpy()
    bus_ids = bus_xy.index.to_numpy()
    k_eff = max(1, min(int(k), bus_ids.shape[0]))

    hub_lmps: dict[str, float] = {}
    for hub in (HUB_BUSAVG, *CUSTOM_HUBS):
        try:
            if hub not in hub_centroids.index:
                continue
            hlat = float(hub_centroids.at[hub, 'lat'])
            hlon = float(hub_centroids.at[hub, 'lon'])
            d2 = (bus_coords[:, 0] - hlat) ** 2 + (bus_coords[:, 1] - hlon) ** 2
            nearest_idx = np.argpartition(d2, k_eff - 1)[:k_eff]
            nearest_ids = bus_ids[nearest_idx]
            hub_lmps[hub] = float(valid.loc[nearest_ids].mean())
        except Exception as e:
            logger.warning("build_hub_lmps[%s] failed: %s", hub, e)
    return hub_lmps


def load_weighted_slack(
    n: pypsa.Network,
    ts: datetime,
    bus_index: list,
) -> np.ndarray:
    """Normalized load-based slack weights aligned to `bus_index` (PTDF column
    order). Negative loads clipped to zero before normalizing. Zero total load
    falls back to uniform 1/n so the distributed-slack shift is still well-defined.
    """
    naive_ts = pd.Timestamp(ts).tz_convert('UTC').tz_localize(None) \
        if pd.Timestamp(ts).tzinfo is not None else pd.Timestamp(ts)
    load_per_load = n.loads_t.p_set.loc[naive_ts]
    load_per_bus = (
        load_per_load.groupby(n.loads['bus']).sum()
        .reindex(bus_index).fillna(0.0)
    )
    w = load_per_bus.clip(lower=0.0).to_numpy(dtype=float)
    total = float(w.sum())
    if total <= 0.0:
        return np.full(len(bus_index), 1.0 / len(bus_index))
    return w / total


def build_load_per_bus(n: pypsa.Network, ts: datetime) -> pd.Series:
    """Per-bus load aggregated from the adapter-scaled time-varying loads
    written into n.loads_t.p_set for this snapshot."""
    naive_ts = pd.Timestamp(ts).tz_convert('UTC').tz_localize(None)
    load_per_load = n.loads_t.p_set.loc[naive_ts]
    return (
        load_per_load.groupby(n.loads['bus']).sum()
        .reindex(n.buses.index).fillna(0.0)
    )


def build_dispatch_per_bus(dispatch: pd.Series, n: pypsa.Network) -> pd.Series:
    """Aggregate per-generator dispatch (from snapshot result, shed already
    excluded) to per-bus totals.

    Buses with no generators remain NaN — callers persisting to Postgres
    treat NaN as NULL so a bus without any generator carries NULL dispatch,
    not a fabricated 0. compute_congestion's gen_weighted path also handles
    NaN correctly (it fillna(0.0) internally when normalizing weights).
    """
    return (
        dispatch.groupby(n.generators.loc[dispatch.index, 'bus']).sum()
        .reindex(n.buses.index)
    )


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
    # Slack-artifact regression signal: if the distributed-slack conversion
    # is undone, the population collapses to ~1 value @4dp with a giant mode.
    rounded = bp.dropna().round(4)
    if not rounded.empty:
        counts = rounded.value_counts()
        print(f"distinct @4dp: {counts.size}  mode-count: {int(counts.iloc[0])}")
    print(f"Top 10 buses by proximity:")
    print(bp.nlargest(10).round(3).to_string())
