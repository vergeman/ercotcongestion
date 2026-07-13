import pypsa
import hashlib
import numpy as np
from scipy.sparse import csgraph
from pypsa.networks import SubNetwork

_ptdf_lodf_cache  = {}


def _determine_topology_for_ptdf(n):
    """Inlined Network.determine_network_topology() minus find_cycles.

    find_cycles builds sub.C (KVL cycle matrix) for AC powerflow KVL
    enforcement. calculate_PTDF / calculate_BODF — the only consumers in
    this pipeline — do not read it.
    """
    A = n.adjacency_matrix(
        branch_components=n.passive_branch_components,
        return_dataframe=False,
    )
    n_components, labels = csgraph.connected_components(A, directed=False)
    for name in list(n.sub_networks.index):
        obj = n.sub_networks.at[name, "obj"]
        n.remove("SubNetwork", name)
        del obj
    for i in np.arange(n_components):
        buses_i = (labels == i).nonzero()[0]
        carrier = n.buses.carrier.iat[buses_i[0]]
        n.add("SubNetwork", i, carrier=carrier)
    n.sub_networks["obj"] = [
        SubNetwork(n, name) for name in n.sub_networks.index
    ]
    n.buses.loc[:, "sub_network"] = labels.astype(str)
    for c in n.iterate_components(n.passive_branch_components):
        c.static["sub_network"] = c.static.bus0.map(n.buses["sub_network"])
    for sub in n.sub_networks.obj:
        sub.find_bus_controls()

def _topology_key(n: pypsa.Network) -> str:
    """Hash based on branch set + reactances. Invalidated when lines/tx change."""
    key = (
        tuple(n.lines.index),
        tuple(n.lines['bus0']), tuple(n.lines['bus1']),
        tuple(n.lines['x'].round(8)),
        tuple(n.transformers.index),
        tuple(n.transformers['bus0']), tuple(n.transformers['bus1']),
        tuple(n.transformers['x'].round(8)),
        tuple(n.buses.index),
    )
    return hashlib.sha1(repr(key).encode()).hexdigest()[:12]

def get_ptdf_lodf(n):
    """Return (PTDF, LODF_lines, bus_names) with caching."""
    k = _topology_key(n)
    if k in _ptdf_lodf_cache:
        return _ptdf_lodf_cache[k]

    _determine_topology_for_ptdf(n)

    # Texas2k is one connected interconnection; 1 sub_network
    sub = n.sub_networks.obj.iloc[0]
    sub.calculate_PTDF()
    sub.calculate_BODF()
    ptdf = np.asarray(sub.PTDF)
    bodf = np.asarray(sub.BODF)
    n_lines = len(n.lines)
    lodf_lines = bodf[:n_lines, :n_lines]
    bus_names = list(sub.buses_o)
    result = (ptdf, lodf_lines, bus_names)
    _ptdf_lodf_cache[k] = result
    return result


def distribute_slack(ptdf_single: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Convert a single-slack PTDF to a distributed-slack PTDF.

    H_dist[l, b] = H[l, b] - Σ_k H[l, k] * w[k]

    `w` must sum to 1 and align to `ptdf_single`'s bus columns. The row shift
    leaves flow sensitivities to a balanced (Σ Δinjection = 0) perturbation
    unchanged and eliminates the artifact where every column collapses to
    ~PTDF[l, slack_line] when the slack bus is topologically radial.
    """
    if w.shape[0] != ptdf_single.shape[1]:
        raise ValueError(
            f"slack weights length {w.shape[0]} does not match "
            f"PTDF bus count {ptdf_single.shape[1]}"
        )
    if not np.isfinite(w).all():
        raise ValueError("slack weights contain non-finite values")
    total = float(w.sum())
    if abs(total - 1.0) > 1e-9:
        raise ValueError(f"slack weights sum {total} != 1.0")
    shift = np.asarray(ptdf_single @ w).reshape(-1, 1)
    return np.subtract(ptdf_single, shift)


def print_network_diagnostic(n):
    if n.generators_t.p.empty:
        print("Network not solved. Run n.optimize() first.")

    # Sanity checks
    gen = n.generators_t.p.iloc[0].sum()
    load = n.loads['p_set'].sum()
    lmps = n.buses_t.marginal_price.iloc[0]

    print(f"\nGen: {gen:.0f} MW | Load: {load:.0f} MW | Balance: {gen - load:+.1f}")
    print(f"LMP: min={lmps.min():.2f}, mean={lmps.mean():.2f}, max={lmps.max():.2f}")
    print(f"LMP p5/p50/p95: {lmps.quantile([0.05, 0.5, 0.95]).round(2).values}")

    print("\nDispatch by fuel:")
    dispatch = n.generators.assign(p=n.generators_t.p.iloc[0])\
                           .groupby('carrier')['p'].sum().sort_values(ascending=False)
    print(dispatch.round(0))
