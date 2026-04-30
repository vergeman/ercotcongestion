import pandas as pd
import numpy as np
import pypsa
import logging
logger = logging.getLogger(__name__)


def compute_fragility(n: pypsa.Network, ptdf_full: np.ndarray, sub_buses: list) -> pd.Series:
    """
    Fragility: Σ PTDF² × shadow / headroom per bus
    """
    logger.debug(f"PTDF shape: {ptdf_full.shape}, "
                 f"branches: {len(n.lines) + len(n.transformers)}")

    shadow_ln, headroom_ln = _compute_shadow(n.lines, n.lines_t)
    shadow_tx, headroom_tx = _compute_shadow(n.transformers, n.transformers_t)

    # Stack: PTDF rows are [lines, transformers]
    weights_full = np.concatenate([shadow_ln / headroom_ln, shadow_tx / headroom_tx])
    fragility_vec = ((ptdf_full ** 2) * weights_full[:, np.newaxis]).sum(axis=0)
    fragility = pd.Series(fragility_vec, index=sub_buses, name='fragility')
    return fragility



# component: lines or transformers
# flow_t: n.lines_t, n.transformers_t
def _compute_shadow(component, flow_t) -> tuple[np.ndarray, np.ndarray]:

    # ---- Gather shadow prices and line data ----
    num = len(component.index)

    # line is congested.
    if flow_t.mu_upper is None or flow_t.mu_upper.empty:
        mu_up = np.zeros(num)
    else:
        mu_up = flow_t.mu_upper.iloc[0].abs().reindex(component.index).fillna(0).values

    # line is congested in the reverse direction.
    if flow_t.mu_lower is None or flow_t.mu_lower.empty:
        mu_lo = np.zeros(num)
    else:
        mu_lo = flow_t.mu_lower.iloc[0].abs().reindex(component.index).fillna(0).values

    shadow = mu_up + mu_lo
    flow = flow_t.p0.iloc[0].abs().reindex(component.index).fillna(0).values
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
