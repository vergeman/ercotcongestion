"""
Hub LMP k-nearest sweep (0049 S4.2).

For each ERCOT hub centroid, model `hub_avg` originally read the single
nearest synthetic bus. That produced HB_NORTH spikes to $2116 and made
HB_WEST negative on 38 of 93 non-shed snapshots (v1-120 backfill).

This script sweeps k over {1,3,5,7,10}, recomputes hub LMPs directly from
persisted per-bus LMPs in model_results.json.gz, and compares against the
ERCOT DAM SPP hub values in ercot_results.json.gz to pick a k. Per-bus LMPs
are reconstructed exactly from `congestion["hub_avg"]` + `hub_lmps["HB_BUSAVG"]`
(the congestion column is stored as `lmps - HB_BUSAVG_ref`, so the sum
recovers the original LMP series to 3-decimal round trip precision).

Usage:
    docker compose run --rm compute python -m compute.experiments.hub_k_sweep.sweep
    docker compose run --rm compute python -m compute.experiments.hub_k_sweep.sweep \
        --model-results /compute/runs/v1-120-postfix/congestion/model_results.json.gz \
        --ercot-results /compute/runs/v1-120/congestion/ercot_results.json.gz \
        --out docs/hub_k_sweep.md
"""
import argparse
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pypsa

from compute.config import NETWORK_NC
from compute.congestion.compute import CUSTOM_HUBS, HUB_BUSAVG


HUBS = (HUB_BUSAVG, *CUSTOM_HUBS)
K_VALUES = (1, 5, 25, 100, 200, 300, 500, 1000, 2000)
SPIKE_ABS = 500.0
HUB_CENTROIDS_CSV = Path("/data/processed/hubs_lz_centroids.csv")
DEFAULT_MODEL = Path("/compute/runs/v1-120-postfix/congestion/model_results.json.gz")
DEFAULT_ERCOT = Path("/compute/runs/v1-120/congestion/ercot_results.json.gz")
DEFAULT_OUT = Path("/compute/experiments/hub_k_sweep/hub_k_sweep.md")


def _load_json_gz(path: Path) -> list[dict]:
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt") as f:
        return json.load(f)


def _reconstruct_lmps(rec: dict) -> pd.Series | None:
    """lmps[b] = cong["hub_avg"][b] + hub_lmps["HB_BUSAVG"]. Returns None if
    the record is missing either piece."""
    cong = (rec.get("congestion") or {}).get("hub_avg")
    hubs = rec.get("hub_lmps") or {}
    ref = hubs.get(HUB_BUSAVG)
    if not cong or ref is None:
        return None
    s = pd.Series(cong, dtype=float) + float(ref)
    s.index = s.index.astype(str)
    return s


def _hub_knn_indices(
    bus_coords: np.ndarray,
    bus_ids: np.ndarray,
    hub_centroids: pd.DataFrame,
    k_max: int,
) -> dict[str, np.ndarray]:
    """Precompute the top-k_max nearest bus ids per hub (sorted by distance).
    Slicing [:k] then gives the k-nearest set for any k <= k_max."""
    out: dict[str, np.ndarray] = {}
    for hub in HUBS:
        if hub not in hub_centroids.index:
            continue
        hlat = float(hub_centroids.at[hub, "lat"])
        hlon = float(hub_centroids.at[hub, "lon"])
        d2 = (bus_coords[:, 0] - hlat) ** 2 + (bus_coords[:, 1] - hlon) ** 2
        order = np.argsort(d2)[:k_max]
        out[hub] = bus_ids[order]
    return out


def _stats(model: pd.Series, ercot: pd.Series) -> dict:
    m = model.dropna()
    e = ercot.dropna()
    joined = pd.concat([m.rename("m"), e.rename("e")], axis=1).dropna()
    if joined.empty:
        return {"n": 0}
    corr = joined["m"].corr(joined["e"])
    ratio = (joined["m"] / joined["e"].replace(0, np.nan)).dropna()
    return {
        "n": int(joined.shape[0]),
        "mean": float(m.mean()),
        "p5": float(m.quantile(0.05)),
        "p50": float(m.quantile(0.50)),
        "p95": float(m.quantile(0.95)),
        "min": float(m.min()),
        "max": float(m.max()),
        "corr": float(corr) if pd.notna(corr) else float("nan"),
        "median_ratio": float(ratio.median()) if not ratio.empty else float("nan"),
        "n_spike": int((m.abs() > SPIKE_ABS).sum()),
        "n_negative": int((m < 0).sum()),
        "ercot_mean": float(e.mean()),
        "ercot_p50": float(e.quantile(0.50)),
    }


def _fmt(v, spec=".2f"):
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return "nan"
    return format(v, spec)


def _hub_table_md(hub: str, per_k: dict[int, dict]) -> str:
    ercot = next(iter(per_k.values()))
    header = (
        f"### {hub}  \n"
        f"ERCOT DAM SPP over the matched window: "
        f"mean=${_fmt(ercot['ercot_mean'])} p50=${_fmt(ercot['ercot_p50'])} "
        f"(n={ercot['n']})\n\n"
        "| k | mean | p5 | p50 | p95 | min | max | corr | med_ratio | n_spike(|x|>500) | n_neg |\n"
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n"
    )
    rows = []
    for k, s in per_k.items():
        rows.append(
            f"| {k} | {_fmt(s['mean'])} | {_fmt(s['p5'])} | {_fmt(s['p50'])} | "
            f"{_fmt(s['p95'])} | {_fmt(s['min'])} | {_fmt(s['max'])} | "
            f"{_fmt(s['corr'], '.3f')} | {_fmt(s['median_ratio'], '.3f')} | "
            f"{s['n_spike']} | {s['n_negative']} |"
        )
    return header + "\n".join(rows) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-results", type=Path, default=DEFAULT_MODEL)
    ap.add_argument("--ercot-results", type=Path, default=DEFAULT_ERCOT)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    model_recs = _load_json_gz(args.model_results)
    ercot_recs = _load_json_gz(args.ercot_results)

    ercot_by_ts: dict[str, dict[str, float]] = {}
    for r in ercot_recs:
        if r.get("status") != "ok":
            continue
        hubs = r.get("hub_lmps") or {}
        ercot_by_ts[r["ts"]] = {h: float(v) for h, v in hubs.items() if v is not None}

    n = pypsa.Network(NETWORK_NC)
    hub_centroids = pd.read_csv(HUB_CENTROIDS_CSV).set_index("settlement_point")
    bus_xy = n.buses[["y", "x"]].rename(columns={"y": "lat", "x": "lon"}).dropna()
    bus_coords_full = bus_xy[["lat", "lon"]].to_numpy()
    bus_ids_full = bus_xy.index.astype(str).to_numpy()
    k_max = max(K_VALUES)
    knn_top = _hub_knn_indices(bus_coords_full, bus_ids_full, hub_centroids, k_max)

    # For each snapshot, for each k, for each hub -> model value.
    model_by_k: dict[int, dict[str, dict[str, float]]] = {
        k: {h: {} for h in HUBS} for k in K_VALUES
    }
    ercot_by_hub: dict[str, dict[str, float]] = {h: {} for h in HUBS}
    n_matched = 0
    n_no_ercot = 0
    n_no_lmps = 0

    for rec in model_recs:
        if rec.get("status") != "ok":
            continue
        ts = rec["ts"]
        ercot_hubs = ercot_by_ts.get(ts)
        if not ercot_hubs:
            n_no_ercot += 1
            continue
        lmps = _reconstruct_lmps(rec)
        if lmps is None:
            n_no_lmps += 1
            continue
        n_matched += 1
        for hub, ranked_ids in knn_top.items():
            ercot_val = ercot_hubs.get(hub)
            if ercot_val is None:
                continue
            ercot_by_hub[hub][ts] = ercot_val
            for k in K_VALUES:
                ids_k = ranked_ids[:k]
                vals = lmps.reindex(ids_k).dropna()
                if vals.empty:
                    continue
                model_by_k[k][hub][ts] = float(vals.mean())

    print(f"matched snapshots: {n_matched}  no_ercot: {n_no_ercot}  no_lmps: {n_no_lmps}")

    md_lines = [
        "# Hub LMP k-nearest sweep",
        "",
        "Model `hub_avg` averages the k synthetic buses nearest each ERCOT hub "
        "centroid. This sweep re-derives per-bus LMPs from the persisted "
        "`hub_avg` congestion column of the v1-120-postfix backfill and "
        "compares each k against the ERCOT DAM SPP for the same timestamps.",
        "",
        f"* Snapshots matched: {n_matched}",
        f"* Model results: `{args.model_results}`",
        f"* ERCOT results: `{args.ercot_results}`",
        "",
    ]
    aggregate_ratios = {k: [] for k in K_VALUES}
    aggregate_spikes = {k: 0 for k in K_VALUES}
    aggregate_neg = {k: 0 for k in K_VALUES}

    for hub in HUBS:
        per_k = {}
        ercot_series = pd.Series(ercot_by_hub[hub], dtype=float)
        if ercot_series.empty:
            continue
        for k in K_VALUES:
            model_series = pd.Series(model_by_k[k][hub], dtype=float)
            per_k[k] = _stats(model_series, ercot_series)
            if per_k[k]["n"] > 0:
                aggregate_ratios[k].append(per_k[k]["median_ratio"])
                aggregate_spikes[k] += per_k[k]["n_spike"]
                aggregate_neg[k] += per_k[k]["n_negative"]
        md_lines.append(_hub_table_md(hub, per_k))

    md_lines.append("## Summary (across all hubs)\n")
    md_lines.append(
        "| k | mean(|1 - med_ratio|) | total n_spike | total n_neg |\n"
        "|---:|---:|---:|---:|"
    )
    for k in K_VALUES:
        ratios = [r for r in aggregate_ratios[k] if pd.notna(r)]
        drift = float(np.mean([abs(1.0 - r) for r in ratios])) if ratios else float("nan")
        md_lines.append(
            f"| {k} | {_fmt(drift, '.3f')} | {aggregate_spikes[k]} | "
            f"{aggregate_neg[k]} |"
        )
    md_lines.append("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(md_lines))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
