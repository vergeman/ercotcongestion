"""
0012 — congestion matrix joiner.

Consumes a model-side JSON written by `compute.congestion.snapshot_runner`,
runs `compute.congestion.ercot_runner.compute_records` in-process for the
matching (regime, ts) set, builds per-source bus×hour and zone×hour
matrices for each reference method, computes structural diagnostics on
each side, and cross-source agreement (Spearman + KS/Wasserstein) on the
shared hubs and the 8 weather zones.

Usage:
    docker compose run --rm compute python -m compute.matrix \
        --model-results /compute/congestion_results_matrix-smoke.json
"""
import argparse
import gzip
import json
import logging
import math
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from compute.congestion.compute import (
    METHODS,
    aggregate_to_zones,
    distributional_agreement,
    pairwise_corr_distribution,
    pca_variance_explained,
    spearman_rank_agreement,
    split_half_cluster_stability,
)
from compute.congestion import ercot_runner as ercot_snap

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
RUNS_ROOT = BASE_DIR / "runs"
HUB_CENTROIDS_CSV = Path("/data/processed/hubs_lz_centroids.csv")
BUS_WEATHER_LOAD_ZONES_CSV = Path("/data/processed/bus_ercot_weather_load_zones.csv")

# Cross-source hub keys. Model uses the synthetic bus nearest each hub
# centroid (computed below); ERCOT uses the SP directly. HB_PAN and HB_HUBAVG
# exist in the centroid file but not the model's hub_lmps dict — we still
# compare them when both sides resolve.
HUB_KEYS = ("HB_BUSAVG", "HB_HOUSTON", "HB_NORTH", "HB_SOUTH", "HB_WEST")


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _load_model_records(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt') as f:
        records = json.load(f)
    if not isinstance(records, list):
        raise ValueError(f"{path}: expected list of records")
    return records


def _bus_zone_map() -> pd.Series:
    df = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    df['ercot_weather_zone'] = (
        df['ercot_weather_zone'].astype(str).str.lower().str.replace(' ', '_')
    )
    return df.set_index(df['name'].astype(str))['ercot_weather_zone']


def _bus_coords() -> pd.DataFrame:
    df = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    return df.set_index(df['name'].astype(str))[['lat', 'lon']].dropna()


def _hub_to_nearest_bus(coords: pd.DataFrame) -> dict[str, str]:
    """Map each hub centroid to the model bus name closest in lat/lon
    (mirrors `congestion_snapshot.build_hub_lmps`)."""
    hubs = pd.read_csv(HUB_CENTROIDS_CSV).set_index('settlement_point')
    bus_coords = coords[['lat', 'lon']].to_numpy()
    bus_names = coords.index.to_numpy()
    out: dict[str, str] = {}
    for hub in HUB_KEYS:
        if hub not in hubs.index:
            continue
        hlat = float(hubs.at[hub, 'lat'])
        hlon = float(hubs.at[hub, 'lon'])
        d2 = (bus_coords[:, 0] - hlat) ** 2 + (bus_coords[:, 1] - hlon) ** 2
        out[hub] = str(bus_names[int(np.argmin(d2))])
    return out


# ---------------------------------------------------------------------------
# Matrix assembly
# ---------------------------------------------------------------------------

def _col_key(regime: str, ts: str) -> str:
    return f"{regime}|{ts}"


def _build_matrix(records: list[dict], ref_method: str) -> pd.DataFrame:
    """Bus × (regime|ts) congestion matrix from a list of OK records."""
    cols: dict[str, pd.Series] = {}
    for r in records:
        if r.get('status') != 'ok':
            continue
        per_bus = (r.get('congestion') or {}).get(ref_method)
        if not per_bus:
            continue
        key = _col_key(r['regime'], r['ts'])
        cols[key] = pd.Series(per_bus, dtype=float)
    if not cols:
        return pd.DataFrame()
    return pd.DataFrame(cols).sort_index(axis=1)


def _drop_nan_buses(C: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Drop any bus row with at least one NaN across hours.

    Mirrors `pca_variance_explained`'s row-drop so the npz matrix matches
    what diagnostics see.
    """
    if C.empty:
        return C, 0
    X = C.dropna(axis=0, how='any')
    return X, int(C.shape[0] - X.shape[0])


def _write_matrices_npz(
    path: Path,
    matrices_by_ref: dict[str, dict[str, np.ndarray]],
    indices: dict[str, np.ndarray],
) -> None:
    """Persist per-(ref_method, source) bus×hour matrices alongside their
    aligned bus/SP and hour index arrays via ``np.savez_compressed``.

    ``matrices_by_ref[ref] = {"model_C": ndarray, "ercot_C": ndarray}``;
    either side may be a zero-shape array for one-sided ref methods.
    ``indices`` carries the aligned id/hour arrays keyed by
    ``{ref}_model_bus_ids``, ``{ref}_ercot_sp_ids``,
    ``{ref}_model_hours``, ``{ref}_ercot_hours``.
    """
    arrays: dict[str, np.ndarray] = {}
    for ref, sides in matrices_by_ref.items():
        arrays[f"{ref}_model_C"] = sides["model_C"]
        arrays[f"{ref}_ercot_C"] = sides["ercot_C"]
    arrays.update(indices)
    np.savez_compressed(path, **arrays)


def _build_bus_loads_mean(records: list[dict]) -> pd.Series:
    """Mean per-bus load across OK model records (used as bus_weight in
    zone aggregation). Buses absent from a record contribute 0 for that
    record (matches the dropped-zeros convention in `congestion_snapshot`)."""
    sums: dict[str, float] = {}
    n_records = 0
    for r in records:
        if r.get('status') != 'ok':
            continue
        bl = r.get('bus_loads') or {}
        if not bl:
            continue
        n_records += 1
        for b, v in bl.items():
            sums[b] = sums.get(b, 0.0) + float(v)
    if n_records == 0:
        return pd.Series(dtype=float)
    return pd.Series({b: v / n_records for b, v in sums.items()})


# ---------------------------------------------------------------------------
# Per-(regime, ts) intersection
# ---------------------------------------------------------------------------

def _model_ts_by_regime(records: list[dict]) -> dict[str, list[str]]:
    """Collect distinct ts strings per regime from OK model records, in
    input order. Used to drive the ERCOT in-process compute."""
    out: dict[str, list[str]] = OrderedDict()
    for r in records:
        if r.get('status') != 'ok':
            continue
        regime = r['regime']
        ts = r['ts']
        bucket = out.setdefault(regime, [])
        if ts not in bucket:
            bucket.append(ts)
    return out


def _intersect(
    model_recs: list[dict],
    ercot_recs: list[dict],
) -> tuple[list[dict], list[dict]]:
    """Restrict both lists to (regime, ts) pairs present and OK in both."""
    e_ok = {(r['regime'], r['ts']): r for r in ercot_recs if r.get('status') == 'ok'}
    m_filtered: list[dict] = []
    e_filtered: list[dict] = []
    for m in model_recs:
        if m.get('status') != 'ok':
            continue
        key = (m['regime'], m['ts'])
        e = e_ok.get(key)
        if e is None:
            continue
        m_filtered.append(m)
        e_filtered.append(e)
    return m_filtered, e_filtered


# ---------------------------------------------------------------------------
# Per-source diagnostics block
# ---------------------------------------------------------------------------

def _per_source_diagnostics(
    C: pd.DataFrame,
    k: int,
    n_splits: int,
    n_components: int,
) -> dict:
    if C.empty:
        return {
            "n_buses": 0,
            "n_hours": 0,
            "pca": None,
            "pairwise_corr": None,
            "cluster_stability": None,
        }
    return {
        "n_buses": int(C.shape[0]),
        "n_hours": int(C.shape[1]),
        "pca": pca_variance_explained(C, n_components=n_components),
        "pairwise_corr": pairwise_corr_distribution(C),
        "cluster_stability": split_half_cluster_stability(C, k=k, n_splits=n_splits),
    }


# ---------------------------------------------------------------------------
# Phase 4 additions: regime slicing + sign agreement + threshold binding
# ---------------------------------------------------------------------------

def _regime_of(col: str) -> str:
    """Extract regime label from a '<regime>|<ts>' column key."""
    return col.split('|', 1)[0] if '|' in col else ''


def _split_columns_by_regime(cols) -> dict[str, list[str]]:
    """Group hour-column keys by regime, preserving order."""
    out: dict[str, list[str]] = OrderedDict()
    for c in cols:
        out.setdefault(_regime_of(c), []).append(c)
    return out


def _by_regime(per_hour_rho: list[dict]) -> dict[str, dict]:
    """Aggregate `per_hour_rho` entries into per-regime summary stats.

    Each entry is `{"hour": "<regime>|<ts>", "rho": float|None, ...}`.
    """
    buckets: dict[str, list[float]] = {}
    for entry in per_hour_rho or []:
        regime = _regime_of(str(entry.get('hour', '')))
        rho = entry.get('rho')
        if rho is None:
            buckets.setdefault(regime, [])
            continue
        buckets.setdefault(regime, []).append(float(rho))
    out: dict[str, dict] = {}
    for regime, vals in buckets.items():
        arr = np.array(vals, dtype=float)
        out[regime] = {
            "n": int(arr.size),
            "mean": float(arr.mean()) if arr.size else None,
            "median": float(np.median(arr)) if arr.size else None,
            "std": float(arr.std(ddof=1)) if arr.size > 1 else 0.0,
            "frac_positive": float((arr > 0).mean()) if arr.size else None,
        }
    return out


def _sign_agreement(
    Z_m: pd.DataFrame,
    Z_e: pd.DataFrame,
    keys: list,
) -> dict:
    """Fraction of hours where sign(model) == sign(ercot), per zone + overall.

    Sign treats 0 as its own class (agrees only with 0). NaN-safe.
    """
    common_keys = [k for k in keys if k in Z_m.index and k in Z_e.index]
    common_hours = [h for h in Z_m.columns if h in Z_e.columns]
    if not common_keys or not common_hours:
        return {"n_keys": 0, "n_hours": 0, "per_key": {}, "overall": None}
    per_key: dict[str, dict] = {}
    all_m: list[np.ndarray] = []
    all_e: list[np.ndarray] = []
    for k in common_keys:
        m = Z_m.loc[k, common_hours].to_numpy(dtype=float)
        e = Z_e.loc[k, common_hours].to_numpy(dtype=float)
        mask = ~(np.isnan(m) | np.isnan(e))
        n = int(mask.sum())
        if n == 0:
            per_key[str(k)] = {"n": 0, "frac_agree": None}
            continue
        agree = (np.sign(m[mask]) == np.sign(e[mask]))
        per_key[str(k)] = {"n": n, "frac_agree": float(agree.mean())}
        all_m.append(m[mask])
        all_e.append(e[mask])
    if all_m:
        M = np.concatenate(all_m)
        E = np.concatenate(all_e)
        overall = {"n": int(M.size),
                   "frac_agree": float((np.sign(M) == np.sign(E)).mean())}
    else:
        overall = None
    return {
        "n_keys": len(common_keys),
        "n_hours": len(common_hours),
        "per_key": per_key,
        "overall": overall,
    }


def _threshold_counts(
    Z: pd.DataFrame,
    keys: list,
    thresholds: tuple[float, ...],
) -> dict:
    """Per key: fraction of hours where |Z[k,h]| > τ, for each τ."""
    common_keys = [k for k in keys if k in Z.index]
    per_key: dict[str, dict] = {}
    for k in common_keys:
        vals = Z.loc[k].to_numpy(dtype=float)
        mask = ~np.isnan(vals)
        n = int(mask.sum())
        if n == 0:
            per_key[str(k)] = {
                "n": 0,
                "fractions": {str(t): None for t in thresholds},
            }
            continue
        v = np.abs(vals[mask])
        per_key[str(k)] = {
            "n": n,
            "fractions": {str(t): float((v > t).mean()) for t in thresholds},
        }
    return {
        "n_keys": len(common_keys),
        "n_hours": int(Z.shape[1]),
        "thresholds": [float(t) for t in thresholds],
        "per_key": per_key,
    }


def _regime_split_apply(
    Z_m: pd.DataFrame,
    Z_e: pd.DataFrame | None,
    fn,
) -> dict[str, dict]:
    """Apply `fn(sub_m, sub_e)` (or `fn(sub_m)` if Z_e is None) per regime."""
    by_reg = _split_columns_by_regime(list(Z_m.columns))
    out: dict[str, dict] = {}
    for regime, cols in by_reg.items():
        sub_m = Z_m[cols]
        if Z_e is None:
            out[regime] = fn(sub_m)
        else:
            e_cols = [c for c in cols if c in Z_e.columns]
            sub_e = Z_e[e_cols]
            out[regime] = fn(sub_m, sub_e)
    return out


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _sanitize(obj):
    """Replace NaN/inf with None so the result round-trips through json."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    return obj


def _resolve_model_path(run_id: str) -> Path:
    """Locate the per-record model results under runs/<run_id>/congestion/.
    Prefer .json.gz; fall back to .json."""
    base = RUNS_ROOT / run_id / "congestion"
    gz_path = base / "model_results.json.gz"
    if gz_path.exists():
        return gz_path
    plain = base / "model_results.json"
    if plain.exists():
        return plain
    raise SystemExit(
        f"model results not found under {base} "
        f"(tried model_results.json.gz, model_results.json)"
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-id', default=None,
                    help='Run identifier. When set, --model-results is derived '
                         'from compute/runs/<run_id>/congestion/ and outputs go '
                         'to compute/runs/<run_id>/matrix/.')
    ap.add_argument('--model-results', type=Path, default=None,
                    help='Explicit path to model per-record JSON (.json or '
                         '.json.gz). Required when --run-id is not set; wins '
                         'over --run-id derivation when both given.')
    ap.add_argument('--ref-methods', nargs='+', default=list(METHODS),
                    choices=list(METHODS),
                    help='Subset of reference methods (default: all 6).')
    ap.add_argument('--k', type=int, default=10,
                    help='K for split-half cluster stability (default 10).')
    ap.add_argument('--n-splits', type=int, default=5,
                    help='Number of random splits for ARI (default 5).')
    ap.add_argument('--n-components', type=int, default=10,
                    help='PCA components to retain (default 10).')
    ap.add_argument('--binding-thresholds', default='5,20',
                    help='Comma-separated $/MWh thresholds for the binding-count '
                         'metric (default "5,20").')
    args = ap.parse_args()

    binding_thresholds = tuple(
        float(x) for x in args.binding_thresholds.split(',') if x.strip()
    )

    if args.model_results is not None:
        model_path = args.model_results
        if not model_path.exists():
            raise SystemExit(f"model results not found: {model_path}")
        # path.stem drops only the last suffix (.gz -> .json), so handle .json.gz too.
        stem = model_path.name.removesuffix('.json.gz').removesuffix('.json')
        run_id = args.run_id or stem.removeprefix('congestion_results_')
        out_dir = RUNS_ROOT / run_id / "matrix" if args.run_id else BASE_DIR
    elif args.run_id is not None:
        run_id = args.run_id
        model_path = _resolve_model_path(run_id)
        out_dir = RUNS_ROOT / run_id / "matrix"
    else:
        raise SystemExit("must pass --run-id or --model-results")

    out_dir.mkdir(parents=True, exist_ok=True)
    if args.run_id is not None:
        out_path = out_dir / "matrix_summary.json"
        npz_path = out_dir / "congestion_matrices.npz"
    else:
        out_path = out_dir / f"congestion_matrix_{run_id}.json"
        npz_path = out_dir / f"congestion_matrices_{run_id}.npz"

    model_recs = _load_model_records(model_path)
    n_model_total = len(model_recs)
    n_model_ok = sum(1 for r in model_recs if r.get('status') == 'ok')
    print(f"model records: {n_model_ok}/{n_model_total} OK")

    ts_by_regime = _model_ts_by_regime(model_recs)
    n_ts = sum(len(v) for v in ts_by_regime.values())
    print(f"requesting ERCOT compute for {n_ts} (regime, ts) pairs across "
          f"{len(ts_by_regime)} regimes")

    ercot_out = ercot_snap.compute_records(
        timestamps_by_regime=ts_by_regime,
        run_id=run_id,
    )
    ercot_recs = ercot_out['records']
    sp_to_zone = ercot_out['sp_to_zone']
    sp_weights = ercot_out['sp_weights']

    n_ercot_ok = sum(1 for r in ercot_recs if r.get('status') == 'ok')
    print(f"ercot records: {n_ercot_ok}/{len(ercot_recs)} OK")

    model_common, ercot_common = _intersect(model_recs, ercot_recs)
    n_common = len(model_common)
    print(f"common (regime, ts) intersection: {n_common}")

    bus_zone = _bus_zone_map()
    bus_weight = _build_bus_loads_mean(model_common)
    if bus_weight.empty:
        logger.warning("no bus_loads in any model record; falling back to "
                       "uniform model bus weights (re-run model snapshot to "
                       "populate bus_loads).")
        bus_weight = pd.Series(1.0, index=bus_zone.index)

    coords = _bus_coords()
    hub_to_bus = _hub_to_nearest_bus(coords)
    # Hub comparison keys must exist on both sides. Model side uses nearest
    # bus; ERCOT side uses the hub SP directly.
    model_hub_keys = {h: hub_to_bus[h] for h in HUB_KEYS if h in hub_to_bus}
    ercot_hub_keys = list(HUB_KEYS)
    zone_keys = sorted(set(bus_zone.dropna().unique()))

    out: dict = {
        "meta": {
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model_results_path": str(model_path),
            "n_records_model": n_model_ok,
            "n_records_ercot": n_ercot_ok,
            "n_common": n_common,
            "ref_methods": list(args.ref_methods),
            "k": args.k,
            "n_splits": args.n_splits,
            "n_components": args.n_components,
            "binding_thresholds": list(binding_thresholds),
            "dates_summary": _dates_summary(model_common),
            "hub_to_model_bus": model_hub_keys,
            "zone_keys": zone_keys,
        },
        "by_ref_method": {},
    }

    matrices_by_ref: dict[str, dict[str, np.ndarray]] = {}
    indices: dict[str, np.ndarray] = {}

    for ref in args.ref_methods:
        print(f"\n--- {ref} ---")
        C_m_raw = _build_matrix(model_common, ref)
        C_e_raw = _build_matrix(ercot_common, ref)
        C_m, n_dropped_m = _drop_nan_buses(C_m_raw)
        C_e, n_dropped_e = _drop_nan_buses(C_e_raw)
        if n_dropped_m:
            print(f"  model: dropped {n_dropped_m}/{C_m_raw.shape[0]} buses with NaN")
        if n_dropped_e:
            print(f"  ercot: dropped {n_dropped_e}/{C_e_raw.shape[0]} SPs with NaN")

        matrices_by_ref[ref] = {
            "model_C": (
                C_m.to_numpy(dtype=float) if not C_m.empty else np.empty((0, 0), dtype=float)
            ),
            "ercot_C": (
                C_e.to_numpy(dtype=float) if not C_e.empty else np.empty((0, 0), dtype=float)
            ),
        }
        indices[f"{ref}_model_bus_ids"] = (
            C_m.index.to_numpy(dtype=str) if not C_m.empty else np.empty((0,), dtype=str)
        )
        indices[f"{ref}_ercot_sp_ids"] = (
            C_e.index.to_numpy(dtype=str) if not C_e.empty else np.empty((0,), dtype=str)
        )
        indices[f"{ref}_model_hours"] = (
            C_m.columns.to_numpy(dtype=str) if not C_m.empty else np.empty((0,), dtype=str)
        )
        indices[f"{ref}_ercot_hours"] = (
            C_e.columns.to_numpy(dtype=str) if not C_e.empty else np.empty((0,), dtype=str)
        )

        # Per-source structural diagnostics (run on raw bus matrices).
        model_block = _per_source_diagnostics(
            C_m, k=args.k, n_splits=args.n_splits, n_components=args.n_components,
        )
        ercot_block = _per_source_diagnostics(
            C_e, k=args.k, n_splits=args.n_splits, n_components=args.n_components,
        )

        # Zone aggregation.
        Z_m = aggregate_to_zones(C_m, bus_zone, bus_weight) if not C_m.empty else pd.DataFrame()
        Z_e = aggregate_to_zones(C_e, sp_to_zone, sp_weights) if not C_e.empty else pd.DataFrame()

        # Cross-source hub comparison: build hub-keyed matrices.
        if not C_m.empty and not C_e.empty and model_hub_keys:
            mhub_rows = {
                h: C_m.loc[bus]
                for h, bus in model_hub_keys.items()
                if bus in C_m.index
            }
            ehub_rows = {
                h: C_e.loc[h]
                for h in ercot_hub_keys
                if h in C_e.index
            }
            shared_hubs = [h for h in HUB_KEYS if h in mhub_rows and h in ehub_rows]
            if shared_hubs:
                M_h = pd.DataFrame({h: mhub_rows[h] for h in shared_hubs}).T
                E_h = pd.DataFrame({h: ehub_rows[h] for h in shared_hubs}).T
                cross_hubs = {
                    "keys": shared_hubs,
                    "spearman": spearman_rank_agreement(M_h, E_h, shared_hubs),
                    "distributional": distributional_agreement(M_h, E_h, shared_hubs),
                }
            else:
                cross_hubs = {"keys": [], "spearman": None, "distributional": None}
        else:
            cross_hubs = {"keys": [], "spearman": None, "distributional": None}

        # Cross-source zone comparison.
        if not Z_m.empty and not Z_e.empty:
            shared_zones = [z for z in zone_keys if z in Z_m.index and z in Z_e.index]
            if shared_zones:
                sp = spearman_rank_agreement(Z_m, Z_e, shared_zones)
                sp["by_regime"] = _by_regime(sp.get("per_hour_rho", []))
                dist = distributional_agreement(Z_m, Z_e, shared_zones)
                dist["by_regime"] = _regime_split_apply(
                    Z_m, Z_e,
                    lambda m, e: distributional_agreement(m, e, shared_zones),
                )
                sign_agree = {
                    "global": _sign_agreement(Z_m, Z_e, shared_zones),
                    "by_regime": _regime_split_apply(
                        Z_m, Z_e,
                        lambda m, e: _sign_agreement(m, e, shared_zones),
                    ),
                }
                thresh = {
                    "model": {
                        "global": _threshold_counts(Z_m, shared_zones, binding_thresholds),
                        "by_regime": _regime_split_apply(
                            Z_m, None,
                            lambda m: _threshold_counts(m, shared_zones, binding_thresholds),
                        ),
                    },
                    "ercot": {
                        "global": _threshold_counts(Z_e, shared_zones, binding_thresholds),
                        "by_regime": _regime_split_apply(
                            Z_e, None,
                            lambda m: _threshold_counts(m, shared_zones, binding_thresholds),
                        ),
                    },
                }
                cross_zones = {
                    "keys": shared_zones,
                    "spearman": sp,
                    "distributional": dist,
                    "sign_agreement": sign_agree,
                    "threshold_binding": thresh,
                }
            else:
                cross_zones = {"keys": [], "spearman": None, "distributional": None,
                               "sign_agreement": None, "threshold_binding": None}
        else:
            cross_zones = {"keys": [], "spearman": None, "distributional": None,
                           "sign_agreement": None, "threshold_binding": None}

        out["by_ref_method"][ref] = {
            "model": model_block,
            "ercot": ercot_block,
            "model_zone_shape": list(Z_m.shape),
            "ercot_zone_shape": list(Z_e.shape),
            "cross_hubs": cross_hubs,
            "cross_zones": cross_zones,
        }

    with open(out_path, 'w') as f:
        json.dump(_sanitize(out), f)
    print(f"\nWrote {out_path}")

    _write_matrices_npz(npz_path, matrices_by_ref, indices)
    print(
        f"wrote {npz_path} (n_refs={len(matrices_by_ref)}, "
        f"total_bytes={npz_path.stat().st_size})"
    )


def _dates_summary(records: list[dict]) -> dict:
    if not records:
        return {"n": 0, "regimes": {}}
    by_regime: dict[str, list[str]] = {}
    for r in records:
        by_regime.setdefault(r['regime'], []).append(r['ts'])
    return {
        "n": len(records),
        "regimes": {k: {"n": len(v), "first": min(v), "last": max(v)}
                    for k, v in by_regime.items()},
    }


if __name__ == '__main__':
    main()
