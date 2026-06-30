"""
Phase 2 congestion calculation.

Computes bus-level congestion as `LMP[bus] - reference_price` under several
reference-price choices, so we can later compare which reference produces the
most spatially coherent / interpretable congestion structure.

Each reference-price method is computed independently — a failure in one
(e.g., missing hub price, missing loads) yields NaN for that column only and
does not affect the others.
"""
import logging

import numpy as np
import pandas as pd
from scipy import stats
from scipy.cluster.vq import kmeans2
from scipy.special import comb

logger = logging.getLogger(__name__)

HUB_BUSAVG = "HB_BUSAVG"
CUSTOM_HUBS = ("HB_HOUSTON", "HB_NORTH", "HB_SOUTH", "HB_WEST")

METHODS = (
    "hub_avg",
    "custom_hub_avg",
    "load_weighted",
    "gen_weighted",
    "system_lambda",
    "system_lambda_kkt",
    "system_lambda_copper_plate",
    "simple_mean",
)


def compute_congestion(
    lmps: pd.Series,
    hub_lmps: dict[str, float] | None = None,
    loads: pd.Series | None = None,
    dispatch: pd.Series | None = None,
    system_lambda: float | None = None,
    system_lambda_kkt: float | None = None,
    system_lambda_copper_plate: float | None = None,
) -> pd.DataFrame:
    """
    Compute bus-level congestion under five reference-price methods.

    Parameters
    ----------
    lmps : pd.Series
        Bus LMPs (index = bus name, values = $/MWh). NaN entries are
        propagated to the output.
    hub_lmps : dict[str, float], optional
        Reference hub prices. Looked-up keys:
          - HB_BUSAVG (for `hub_avg`)
          - HB_HOUSTON, HB_NORTH, HB_SOUTH, HB_WEST (for `custom_hub_avg`)
    loads : pd.Series, optional
        Per-bus load (MW), indexed by bus name. Required for `load_weighted`.
    dispatch : pd.Series, optional
        Per-bus dispatched generation (MW), indexed by bus name. Required for
        `gen_weighted`.
    system_lambda : float, optional
        Energy-component reference price ($/MWh). Required for `system_lambda`.
        Model-side default = `lmps.median()`; ERCOT side = real DAM λ.
    system_lambda_kkt : float, optional
        KKT clean-bus median λ̂ (model-side only). Required for
        `system_lambda_kkt`.
    system_lambda_copper_plate : float, optional
        Two-pass copper-plate λ (model-side only). Required for
        `system_lambda_copper_plate`.

    Returns
    -------
    pd.DataFrame indexed by bus with columns:
      - hub_avg                    : lmps − hub_lmps[HB_BUSAVG]
      - custom_hub_avg             : lmps − mean(four directional hub prices)
      - load_weighted              : lmps − Σ(lmps × loads) / Σ(loads)
      - gen_weighted               : lmps − Σ(lmps × dispatch) / Σ(dispatch)
      - system_lambda              : lmps − system_lambda
      - system_lambda_kkt          : lmps − system_lambda_kkt
      - system_lambda_copper_plate : lmps − system_lambda_copper_plate
      - simple_mean                : lmps − lmps.mean()
    """
    hub_lmps = hub_lmps or {}
    nan_col = pd.Series(np.nan, index=lmps.index)
    out: dict[str, pd.Series] = {m: nan_col.copy() for m in METHODS}

    try:
        ref = hub_lmps[HUB_BUSAVG]
        out["hub_avg"] = lmps - float(ref)
    except Exception as e:
        logger.warning("hub_avg failed: %s", e)

    try:
        prices = [hub_lmps[h] for h in CUSTOM_HUBS if h in hub_lmps]
        if not prices:
            raise KeyError(f"no directional hub prices in hub_lmps (need any of {CUSTOM_HUBS})")
        if len(prices) < len(CUSTOM_HUBS):
            missing = [h for h in CUSTOM_HUBS if h not in hub_lmps]
            logger.warning("custom_hub_avg using partial set; missing %s", missing)
        out["custom_hub_avg"] = lmps - (sum(prices) / len(prices))
    except Exception as e:
        logger.warning("custom_hub_avg failed: %s", e)

    try:
        if loads is None:
            raise ValueError("loads is required for load_weighted")
        aligned = loads.reindex(lmps.index).fillna(0.0)
        valid = lmps.notna()
        total = float(aligned[valid].sum())
        if total <= 0:
            raise ValueError("total load is zero or negative")
        ref = float((lmps[valid] * aligned[valid]).sum() / total)
        out["load_weighted"] = lmps - ref
    except Exception as e:
        logger.warning("load_weighted failed: %s", e)

    try:
        if dispatch is None:
            raise ValueError("dispatch is required for gen_weighted")
        aligned = dispatch.reindex(lmps.index).fillna(0.0)
        valid = lmps.notna()
        total = float(aligned[valid].sum())
        if total <= 0:
            raise ValueError("total dispatch is zero or negative")
        ref = float((lmps[valid] * aligned[valid]).sum() / total)
        out["gen_weighted"] = lmps - ref
    except Exception as e:
        logger.warning("gen_weighted failed: %s", e)

    try:
        if system_lambda is None:
            raise ValueError("system_lambda is required")
        out["system_lambda"] = lmps - float(system_lambda)
    except Exception as e:
        logger.warning("system_lambda failed: %s", e)

    try:
        if system_lambda_kkt is None:
            raise ValueError("system_lambda_kkt is required")
        out["system_lambda_kkt"] = lmps - float(system_lambda_kkt)
    except Exception as e:
        logger.warning("system_lambda_kkt failed: %s", e)

    try:
        if system_lambda_copper_plate is None:
            raise ValueError("system_lambda_copper_plate is required")
        out["system_lambda_copper_plate"] = lmps - float(system_lambda_copper_plate)
    except Exception as e:
        logger.warning("system_lambda_copper_plate failed: %s", e)

    try:
        ref = lmps.mean(skipna=True)
        if pd.isna(ref):
            raise ValueError("all LMPs are NaN")
        out["simple_mean"] = lmps - float(ref)
    except Exception as e:
        logger.warning("simple_mean failed: %s", e)

    return pd.DataFrame(out)


def congestion_diagnostics(cong: pd.DataFrame) -> None:
    """Print per-method summary stats and a few extreme buses."""
    print("\nCongestion stats by method:")
    print(cong.describe(percentiles=[0.05, 0.5, 0.95]).round(2).to_string())

    for method in cong.columns:
        s = cong[method].dropna()
        if s.empty:
            print(f"\n{method}: all NaN")
            continue
        print(f"\n{method} — top 5 positive (export-constrained / cheap-side):")
        print(s.nlargest(5).round(2).to_string())
        print(f"{method} — top 5 negative (import-constrained / expensive-side):")
        print(s.nsmallest(5).round(2).to_string())


# ---------------------------------------------------------------------------
# Phase 2 matrix + structural diagnostics
# ---------------------------------------------------------------------------

def build_congestion_matrix(
    records: list[dict],
    ref_method: str,
) -> pd.DataFrame:
    """Stack per-snapshot congestion dicts into a wide bus×hour matrix.

    Parameters
    ----------
    records
        Output of `congestion_snapshot`. Only records with status=='ok' and
        a populated congestion[ref_method] block are used; others are dropped.
    ref_method
        One of the entries in METHODS.

    Returns
    -------
    DataFrame indexed by bus, columns sorted ts (pd.Timestamp).
    """
    cols: dict[pd.Timestamp, pd.Series] = {}
    for r in records:
        if r.get('status') != 'ok':
            continue
        cong = r.get('congestion') or {}
        per_bus = cong.get(ref_method)
        if not per_bus:
            continue
        ts = pd.Timestamp(r['ts'])
        cols[ts] = pd.Series(per_bus, dtype=float)
    if not cols:
        return pd.DataFrame()
    C = pd.DataFrame(cols).sort_index(axis=1)
    return C


def pca_variance_explained(C: pd.DataFrame, n_components: int = 10) -> dict:
    """PCA on the bus×hour congestion matrix.

    Drops buses with any NaN across hours (cannot center/score them). Logs
    the dropped count. Returns explained-variance ratios and the top
    contributing buses per component.
    """
    X = C.dropna(axis=0, how='any')
    n_dropped = C.shape[0] - X.shape[0]
    if n_dropped:
        logger.info("pca: dropped %d/%d buses with NaN", n_dropped, C.shape[0])
    if X.empty or X.shape[1] < 2:
        return {
            "n_components": 0,
            "n_buses": int(X.shape[0]),
            "n_dropped": int(n_dropped),
            "explained_variance_ratio": [],
            "cumulative": [],
            "top_pc_loadings": [],
        }

    k = max(1, min(n_components, X.shape[0], X.shape[1]))
    # PCA samples = hours (rows), features = buses.
    samples = X.T.to_numpy()
    centered = samples - samples.mean(axis=0, keepdims=True)
    n_samples = centered.shape[0]
    # SVD on the (samples × features) matrix.
    U, S, Vt = np.linalg.svd(centered, full_matrices=False)
    eigenvalues = (S ** 2) / max(n_samples - 1, 1)
    total_var = float(eigenvalues.sum())
    if total_var <= 0:
        evr_full = np.zeros_like(eigenvalues)
    else:
        evr_full = eigenvalues / total_var
    evr = [float(x) for x in evr_full[:k]]
    cum = list(np.cumsum(evr).round(6))

    bus_names = list(X.index)
    top_loadings: list[dict] = []
    for i in range(k):
        loadings = Vt[i]
        order = np.argsort(np.abs(loadings))[::-1][:10]
        top_loadings.append({
            "pc": i + 1,
            "explained_variance_ratio": float(evr[i]),
            "top_buses": [
                {"bus": str(bus_names[j]), "loading": float(loadings[j])}
                for j in order
            ],
        })

    return {
        "n_components": int(k),
        "n_buses": int(X.shape[0]),
        "n_dropped": int(n_dropped),
        "explained_variance_ratio": evr,
        "cumulative": [float(x) for x in cum],
        "top_pc_loadings": top_loadings,
    }


def pairwise_corr_distribution(C: pd.DataFrame, n_bins: int = 20) -> dict:
    """Off-diagonal bus×bus Pearson correlation summary (pairwise-complete).

    Returns mean/median/std/quantiles and a histogram of correlations.
    """
    if C.shape[0] < 2 or C.shape[1] < 2:
        return {
            "n_pairs": 0, "mean": float('nan'), "median": float('nan'),
            "std": float('nan'),
            "q": {k: float('nan') for k in ("p5", "p25", "p50", "p75", "p95")},
            "histogram": {"edges": [], "counts": []},
        }

    # pandas .corr uses pairwise-complete by default.
    R = C.T.corr()
    iu = np.triu_indices(R.shape[0], k=1)
    vals = R.values[iu]
    vals = vals[~np.isnan(vals)]
    if vals.size == 0:
        return {
            "n_pairs": 0, "mean": float('nan'), "median": float('nan'),
            "std": float('nan'),
            "q": {k: float('nan') for k in ("p5", "p25", "p50", "p75", "p95")},
            "histogram": {"edges": [], "counts": []},
        }
    counts, edges = np.histogram(vals, bins=n_bins, range=(-1.0, 1.0))
    qs = np.quantile(vals, [0.05, 0.25, 0.50, 0.75, 0.95])
    return {
        "n_pairs": int(vals.size),
        "mean": float(np.mean(vals)),
        "median": float(np.median(vals)),
        "std": float(np.std(vals, ddof=1)) if vals.size > 1 else 0.0,
        "q": {
            "p5": float(qs[0]), "p25": float(qs[1]),
            "p50": float(qs[2]), "p75": float(qs[3]),
            "p95": float(qs[4]),
        },
        "histogram": {
            "edges": [float(x) for x in edges],
            "counts": [int(x) for x in counts],
        },
    }


def _adjusted_rand_score(labels_a, labels_b) -> float:
    """Adjusted Rand Index. Manual implementation to avoid sklearn dep."""
    a = np.asarray(labels_a)
    b = np.asarray(labels_b)
    if a.size != b.size or a.size < 2:
        return float('nan')
    ua, ai = np.unique(a, return_inverse=True)
    ub, bi = np.unique(b, return_inverse=True)
    cont = np.zeros((ua.size, ub.size), dtype=np.int64)
    for x, y in zip(ai, bi):
        cont[x, y] += 1
    sum_comb_c = float(np.sum(comb(cont, 2, exact=False)))
    sum_a = float(np.sum(comb(cont.sum(axis=1), 2, exact=False)))
    sum_b = float(np.sum(comb(cont.sum(axis=0), 2, exact=False)))
    n = a.size
    total_pairs = comb(n, 2, exact=False)
    if total_pairs == 0:
        return float('nan')
    expected = sum_a * sum_b / total_pairs
    max_index = 0.5 * (sum_a + sum_b)
    if max_index == expected:
        return 1.0 if sum_comb_c == expected else 0.0
    return float((sum_comb_c - expected) / (max_index - expected))


def split_half_cluster_stability(
    C: pd.DataFrame,
    k: int = 10,
    n_splits: int = 5,
    seed: int = 0,
) -> dict:
    """K-means cluster stability across random temporal halves (ARI)."""
    X = C.dropna(axis=0, how='any')
    if X.shape[0] < k or X.shape[1] < 4:
        return {
            "k": int(k), "n_splits": int(n_splits),
            "n_buses_used": int(X.shape[0]),
            "per_split_ari": [], "mean_ari": float('nan'), "std_ari": float('nan'),
        }

    rng = np.random.default_rng(seed)
    n_hours = X.shape[1]
    aris: list[float] = []
    for s in range(n_splits):
        perm = rng.permutation(n_hours)
        half = n_hours // 2
        a_idx, b_idx = perm[:half], perm[half:half * 2]
        A = X.iloc[:, a_idx].to_numpy().astype(float)
        B = X.iloc[:, b_idx].to_numpy().astype(float)
        try:
            _, la = kmeans2(A, k, minit='++', seed=seed + s, missing='warn')
            _, lb = kmeans2(B, k, minit='++', seed=seed + s + 1000, missing='warn')
            aris.append(_adjusted_rand_score(la, lb))
        except Exception as e:
            logger.warning("split_half[%d] failed: %s", s, e)

    if not aris:
        return {
            "k": int(k), "n_splits": int(n_splits),
            "n_buses_used": int(X.shape[0]),
            "per_split_ari": [], "mean_ari": float('nan'), "std_ari": float('nan'),
        }
    return {
        "k": int(k), "n_splits": int(n_splits),
        "n_buses_used": int(X.shape[0]),
        "per_split_ari": aris,
        "mean_ari": float(np.mean(aris)),
        "std_ari": float(np.std(aris, ddof=1)) if len(aris) > 1 else 0.0,
    }


# ---------------------------------------------------------------------------
# Cross-source agreement + zonal aggregation
# ---------------------------------------------------------------------------

def spearman_rank_agreement(
    C_m: pd.DataFrame,
    C_e: pd.DataFrame,
    keys: list,
) -> dict:
    """Per-hour Spearman rank correlation across `keys` between model and ERCOT.

    Both matrices must share columns (hours). For each hour, rank the values
    at `keys` and correlate.
    """
    common_keys = [k for k in keys if k in C_m.index and k in C_e.index]
    common_hours = [h for h in C_m.columns if h in C_e.columns]
    if len(common_keys) < 3 or not common_hours:
        return {
            "n_keys": len(common_keys),
            "n_hours": len(common_hours),
            "per_hour_rho": [],
            "summary": {
                "mean": float('nan'), "std": float('nan'),
                "frac_positive": float('nan'),
            },
        }

    M = C_m.loc[common_keys, common_hours]
    E = C_e.loc[common_keys, common_hours]
    rhos: list[dict] = []
    vals: list[float] = []
    for h in common_hours:
        mv = M[h].to_numpy(dtype=float)
        ev = E[h].to_numpy(dtype=float)
        mask = ~(np.isnan(mv) | np.isnan(ev))
        if mask.sum() < 3:
            rhos.append({"hour": str(h), "rho": None, "n": int(mask.sum())})
            continue
        rho, _ = stats.spearmanr(mv[mask], ev[mask])
        if np.isnan(rho):
            rhos.append({"hour": str(h), "rho": None, "n": int(mask.sum())})
            continue
        vals.append(float(rho))
        rhos.append({"hour": str(h), "rho": float(rho), "n": int(mask.sum())})

    if not vals:
        summary = {"mean": float('nan'), "std": float('nan'), "frac_positive": float('nan')}
    else:
        arr = np.array(vals)
        summary = {
            "mean": float(arr.mean()),
            "std": float(arr.std(ddof=1)) if arr.size > 1 else 0.0,
            "frac_positive": float((arr > 0).mean()),
        }
    return {
        "n_keys": len(common_keys),
        "n_hours": len(common_hours),
        "per_hour_rho": rhos,
        "summary": summary,
    }


def distributional_agreement(
    C_m: pd.DataFrame,
    C_e: pd.DataFrame,
    keys: list,
) -> dict:
    """Per-key KS test + Wasserstein distance between model and ERCOT
    distributions over the shared hour set."""
    common_keys = [k for k in keys if k in C_m.index and k in C_e.index]
    common_hours = [h for h in C_m.columns if h in C_e.columns]

    per_key: dict[str, dict] = {}
    for k in common_keys:
        mv = C_m.loc[k, common_hours].to_numpy(dtype=float)
        ev = C_e.loc[k, common_hours].to_numpy(dtype=float)
        m_clean = mv[~np.isnan(mv)]
        e_clean = ev[~np.isnan(ev)]
        if m_clean.size < 2 or e_clean.size < 2:
            per_key[str(k)] = {
                "ks_stat": None, "ks_p": None, "wasserstein": None,
                "n_model": int(m_clean.size), "n_ercot": int(e_clean.size),
            }
            continue
        ks = stats.ks_2samp(m_clean, e_clean)
        w = float(stats.wasserstein_distance(m_clean, e_clean))
        per_key[str(k)] = {
            "ks_stat": float(ks.statistic),
            "ks_p": float(ks.pvalue),
            "wasserstein": w,
            "n_model": int(m_clean.size),
            "n_ercot": int(e_clean.size),
            "model_summary": {
                "mean": float(m_clean.mean()),
                "std": float(m_clean.std(ddof=1)) if m_clean.size > 1 else 0.0,
                "p50": float(np.median(m_clean)),
            },
            "ercot_summary": {
                "mean": float(e_clean.mean()),
                "std": float(e_clean.std(ddof=1)) if e_clean.size > 1 else 0.0,
                "p50": float(np.median(e_clean)),
            },
        }
    return {
        "n_keys": len(common_keys),
        "n_hours": len(common_hours),
        "per_key": per_key,
    }


def aggregate_to_zones(
    C: pd.DataFrame,
    bus_zone: pd.Series,
    bus_weight: pd.Series,
) -> pd.DataFrame:
    """Load-weighted-mean aggregation of bus×hour congestion to zone×hour.

    Buses with no zone assignment are dropped. Per zone, weights are
    normalized to sum to 1 over buses present in that zone with finite
    values that hour (NaN-aware).
    """
    if C.empty:
        return pd.DataFrame()

    zones = bus_zone.reindex(C.index)
    weights = bus_weight.reindex(C.index).fillna(0.0).astype(float)
    mask = zones.notna()
    C = C.loc[mask]
    zones = zones.loc[mask]
    weights = weights.loc[mask]
    if C.empty:
        return pd.DataFrame()

    out_rows: dict = {}
    for z, group in C.groupby(zones):
        w = weights.loc[group.index].to_numpy()
        vals = group.to_numpy(dtype=float)
        valid = ~np.isnan(vals)
        w_b = np.broadcast_to(w[:, None], vals.shape) * valid
        num = np.nansum(np.where(valid, vals * w[:, None], 0.0), axis=0)
        denom = w_b.sum(axis=0)
        row = np.where(denom > 0, num / np.where(denom > 0, denom, 1.0), np.nan)
        out_rows[z] = row
    return pd.DataFrame(out_rows, index=C.columns).T.sort_index()
