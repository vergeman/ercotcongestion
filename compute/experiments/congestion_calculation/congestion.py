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

logger = logging.getLogger(__name__)

HUB_BUSAVG = "HB_BUSAVG"
CUSTOM_HUBS = ("HB_HOUSTON", "HB_NORTH", "HB_SOUTH", "HB_WEST")

METHODS = (
    "hub_avg",
    "custom_hub_avg",
    "load_weighted",
    "gen_weighted",
    "system_lambda",
    "simple_mean",
)


def compute_congestion(
    lmps: pd.Series,
    hub_lmps: dict[str, float] | None = None,
    loads: pd.Series | None = None,
    dispatch: pd.Series | None = None,
    system_lambda: float | None = None,
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

    Returns
    -------
    pd.DataFrame indexed by bus with columns:
      - hub_avg        : lmps − hub_lmps[HB_BUSAVG]
      - custom_hub_avg : lmps − mean(four directional hub prices)
      - load_weighted  : lmps − Σ(lmps × loads) / Σ(loads)
      - gen_weighted   : lmps − Σ(lmps × dispatch) / Σ(dispatch)
      - system_lambda  : lmps − system_lambda
      - simple_mean    : lmps − lmps.mean()
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
    """PCA on the congestion matrix. Deferred to Phase 4 — only meaningful
    when comparing model-side vs ERCOT-side matrices side-by-side."""
    raise NotImplementedError("deferred to Phase 4")


def pairwise_corr_distribution(C: pd.DataFrame, n_bins: int = 20) -> dict:
    """Off-diagonal bus×bus correlation summary. Deferred to Phase 4."""
    raise NotImplementedError("deferred to Phase 4")


def split_half_cluster_stability(
    C: pd.DataFrame,
    k: int = 10,
    n_splits: int = 5,
    seed: int = 0,
) -> dict:
    """Split-half cluster stability via Adjusted Rand Index. Deferred to
    Phase 4."""
    raise NotImplementedError("deferred to Phase 4")
