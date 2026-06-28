import pandas as pd
import numpy as np
import pypsa
import logging
logger = logging.getLogger(__name__)


def compute_fragility_at(
    n: pypsa.Network,
    line_mu_upper: pd.Series | None,
    line_mu_lower: pd.Series | None,
    line_p0: pd.Series | None,
    tx_mu_upper: pd.Series | None,
    tx_mu_lower: pd.Series | None,
    tx_p0: pd.Series | None,
    ptdf_full: np.ndarray,
    sub_buses: list,
) -> pd.Series:
    """
    Fragility at a single snapshot: Σ PTDF² × shadow / headroom per bus.

    Series args are 1-D slices (e.g. n.lines_t.mu_upper.loc[ts]). Pass None
    if duals/flows are absent for that component at this snapshot.
    """
    logger.debug(f"PTDF shape: {ptdf_full.shape}, "
                 f"branches: {len(n.lines) + len(n.transformers)}")

    shadow_ln, headroom_ln = _compute_shadow_at(
        n.lines, line_mu_upper, line_mu_lower, line_p0
    )
    shadow_tx, headroom_tx = _compute_shadow_at(
        n.transformers, tx_mu_upper, tx_mu_lower, tx_p0
    )

    # Stack: PTDF rows are [lines, transformers]
    weights_full = np.concatenate([shadow_ln / headroom_ln, shadow_tx / headroom_tx])
    fragility_vec = ((ptdf_full ** 2) * weights_full[:, np.newaxis]).sum(axis=0)
    fragility = pd.Series(fragility_vec, index=sub_buses, name='fragility')
    return fragility



def _compute_shadow_at(
    component,
    mu_upper: pd.Series | None,
    mu_lower: pd.Series | None,
    p0: pd.Series | None,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-snapshot shadow / headroom arrays aligned to component.index."""

    num = len(component.index)

    if mu_upper is None:
        mu_up = np.zeros(num)
    else:
        mu_up = mu_upper.abs().reindex(component.index).fillna(0).values

    if mu_lower is None:
        mu_lo = np.zeros(num)
    else:
        mu_lo = mu_lower.abs().reindex(component.index).fillna(0).values

    shadow = mu_up + mu_lo

    if p0 is None:
        flow = np.zeros(num)
    else:
        flow = p0.abs().reindex(component.index).fillna(0).values

    s_nom = component['s_nom'].values
    headroom = np.maximum(s_nom - flow, 1.0)  # floor at 1 MW to avoid divide-by-zero

    return shadow, headroom

def fragility_diagnostics(frag):

    print(f"\nFragility stats:")
    print(frag.describe())
    print(f"\nTop 10 most fragile buses:")
    print(frag.sort_values(ascending=False).head(10))

    # Concentration — how many buses are meaningfully fragile?
    total_frag = frag.sum()
    mean_frag = frag.mean()
    p95 = frag.quantile(0.95)
    p99 = frag.quantile(0.99)

    print(f"Fragility: total={total_frag:.2f}, mean={mean_frag:.4f}, p95={p95:.4f}, p99={p99:.4f}")
    print(f"Buses above p95 ({p95:.3f}): {(frag > p95).sum()}")
    print(f"Buses above p99 ({p99:.3f}): {(frag > p99).sum()}")
    print(f"Buses with fragility > 0.1: {(frag > 0.1).sum()}")
    print(f"Buses with fragility > 0.01: {(frag > 0.01).sum()}")

    # Concentration ratio — what fraction of total fragility is in the top 10 buses?
    if total_frag > 0:
        top10_share = frag.nlargest(10).sum() / total_frag
        print(f"Top 10 buses hold {top10_share:.1%} of total fragility")

#
# PLOT
#
import matplotlib.pyplot as plt

def fragility_plot(n, frag):

    # Build a dataframe with coords + fragility
    frag_map = pd.DataFrame({
        'x': n.buses.loc[frag.index, 'x'],
        'y': n.buses.loc[frag.index, 'y'],
        'fragility': frag.values
    }).dropna()

    # Plot, log scale for readability
    fig, ax = plt.subplots(figsize=(10, 8))
    sc = ax.scatter(frag_map['x'], frag_map['y'],
                    c=np.log10(frag_map['fragility'].clip(lower=1e-6)),
                    cmap='plasma', s=3, alpha=0.7)
    plt.colorbar(sc, label='log10(fragility)')

    # Highlight the top-5 buses
    top5 = frag.nlargest(5).index
    ax.scatter(n.buses.loc[top5, 'x'], n.buses.loc[top5, 'y'],
               s=100, edgecolor='red', facecolor='none', linewidth=2,
               label='Top 5 most fragile')
    ax.legend()
    ax.set_title('Fragility map (log scale)')
    plt.savefig('fragility_map.png', dpi=120)
    plt.show()
    plt.close('all')
