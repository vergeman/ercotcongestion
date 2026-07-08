"""
Hub LMP k-nearest sweep (0068).

For each ERCOT hub centroid, model `hub_avg` originally read the single
nearest synthetic bus. That produced HB_NORTH spikes to $2116 and made
HB_WEST negative on 38 of 93 non-shed snapshots (v1-120 backfill).

This script sweeps k over K_VALUES, reads per-bus model LMPs directly from
`bus_snapshots`, joins ERCOT DAM SPP hub values from `ercot_dam_spp`, and
picks the k that clears the spike/negative/drift gate.

Usage:
    docker compose run --rm compute python \\
        -m compute.calibration.hub_k_sweep.sweep --start 2025-01-01 --end 2026-07-01
    docker compose run --rm compute python \\
        -m compute.calibration.hub_k_sweep.sweep \\
        --dates-file /compute/sample_specs/reference_dates_120.json \\
        --out /compute/calibration/hub_k_sweep/hub_k_sweep.md
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

from compute.config import NETWORK_BUS_COORDS_CSV, PG_DSN
from compute.congestion.compute import CUSTOM_HUBS, HUB_BUSAVG


HUBS = (HUB_BUSAVG, *CUSTOM_HUBS)
K_VALUES = (1, 5, 25, 100, 200, 300, 500, 1000, 2000)
SPIKE_ABS = 500.0
DRIFT_GATE = 0.05
HUB_CENTROIDS_CSV = Path("/data/processed/hubs_lz_centroids.csv")
DEFAULT_START = "2025-01-01"
DEFAULT_END = "2026-07-01"
DEFAULT_OUT = Path("/compute/calibration/hub_k_sweep/hub_k_sweep.md")


def _coerce_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


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


def _fetch_ok_timestamps(
    conn, start: datetime, end: datetime
) -> list[datetime]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT interval_ts FROM snapshot_meta "
            "WHERE status = 'ok' AND interval_ts BETWEEN %s AND %s "
            "ORDER BY interval_ts",
            (start, end),
        )
        return [row[0] for row in cur.fetchall()]


def _fetch_ercot_hub_spp(
    conn, ts_list: list[datetime]
) -> dict[str, dict[datetime, float]]:
    """Return {hub: {ts: dam_spp}} for HUBS present in ercot_dam_spp.
    DST-safe (mirrors compute/ercot/transforms.py)."""
    out: dict[str, dict[datetime, float]] = {h: {} for h in HUBS}
    if not ts_list:
        return out
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (interval_ts, settlement_point)
                   interval_ts, settlement_point, dam_spp
            FROM ercot_dam_spp
            WHERE interval_ts = ANY(%s) AND settlement_point = ANY(%s)
            ORDER BY interval_ts, settlement_point, dst_flag ASC
            """,
            (ts_list, list(HUBS)),
        )
        for ts, sp, v in cur:
            if sp in out:
                out[sp][ts] = float(v)
    return out


def _stream_model_hub_means(
    conn,
    ts_list: list[datetime],
    knn_top: dict[str, np.ndarray],
) -> dict[int, dict[str, dict[datetime, float]]]:
    """Stream bus_snapshots.lmp, accumulate k-nearest sum+count per
    (k, hub, ts) incrementally, and return the mean per (k, hub, ts). No
    per-ts pd.Series is ever materialized."""
    # bus_id -> list[(hub, pos)] for buses in some hub's top-k_max ranking.
    bus_hub_pos: dict[str, list[tuple[str, int]]] = {}
    for hub, ranked in knn_top.items():
        for pos, bid in enumerate(ranked):
            bus_hub_pos.setdefault(str(bid), []).append((hub, int(pos)))

    sum_by_k: dict[int, dict[str, dict[datetime, float]]] = {
        k: {h: {} for h in knn_top} for k in K_VALUES
    }
    cnt_by_k: dict[int, dict[str, dict[datetime, int]]] = {
        k: {h: {} for h in knn_top} for k in K_VALUES
    }

    with conn.cursor(name='hub_k_sweep_stream') as cur:
        cur.itersize = 10_000
        cur.execute(
            "SELECT interval_ts, bus_id, lmp FROM bus_snapshots "
            "WHERE interval_ts = ANY(%s) AND lmp IS NOT NULL",
            (ts_list,),
        )
        for ts, bus_id, lmp in cur:
            hubs_pos = bus_hub_pos.get(str(bus_id))
            if not hubs_pos:
                continue
            lmp_f = float(lmp)
            for hub, pos in hubs_pos:
                for k in K_VALUES:
                    if pos < k:
                        sum_by_k[k][hub][ts] = sum_by_k[k][hub].get(ts, 0.0) + lmp_f
                        cnt_by_k[k][hub][ts] = cnt_by_k[k][hub].get(ts, 0) + 1

    mean_by_k: dict[int, dict[str, dict[datetime, float]]] = {
        k: {h: {} for h in knn_top} for k in K_VALUES
    }
    for k in K_VALUES:
        for hub in knn_top:
            counts = cnt_by_k[k][hub]
            sums = sum_by_k[k][hub]
            for ts, c in counts.items():
                if c > 0:
                    mean_by_k[k][hub][ts] = sums[ts] / c
    return mean_by_k


def _stats(model: pd.Series, ercot: pd.Series) -> dict:
    m = model.dropna()
    e = ercot.dropna()
    joined = pd.concat([m.rename("m"), e.rename("e")], axis=1, sort=False).dropna()
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


def _pick_k(
    aggregate_drift: dict[int, float],
    aggregate_spikes: dict[int, int],
    aggregate_neg: dict[int, int],
) -> tuple[int, str]:
    """Return (k, rationale). Smallest k with no spike, no negative, and
    mean(|1 − med_ratio|) ≤ DRIFT_GATE (tie-break: lowest drift). Fallback:
    k with lowest drift overall."""
    passing = [
        k for k in K_VALUES
        if aggregate_spikes[k] == 0
        and aggregate_neg[k] == 0
        and not np.isnan(aggregate_drift[k])
        and aggregate_drift[k] <= DRIFT_GATE
    ]
    if passing:
        best = min(passing, key=lambda k: (k, aggregate_drift[k]))
        return best, (
            f"smallest k with no spike / no negative and drift ≤ {DRIFT_GATE:.2f}"
        )
    with_drift = [k for k in K_VALUES if not np.isnan(aggregate_drift[k])]
    if not with_drift:
        return K_VALUES[0], "no k had valid drift data; defaulting to smallest k"
    best = min(with_drift, key=lambda k: aggregate_drift[k])
    return best, "no k cleared the gate; showing lowest-drift"


def _load_dates_file(path: Path) -> list[datetime]:
    with open(path, "r") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        flat = list(raw)
    elif isinstance(raw, dict):
        flat = [ts for ts_list in raw.values() for ts in ts_list]
    else:
        raise ValueError(
            f"{path}: expected list[str] or dict[str, list[str]], "
            f"got {type(raw).__name__}"
        )
    out: list[datetime] = []
    seen: set[datetime] = set()
    for s in flat:
        ts = _coerce_utc(datetime.fromisoformat(s))
        if ts in seen:
            continue
        seen.add(ts)
        out.append(ts)
    out.sort()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=DEFAULT_START,
                    help=f"UTC start (inclusive). Default: {DEFAULT_START}.")
    ap.add_argument("--end", default=DEFAULT_END,
                    help=f"UTC end (inclusive). Default: {DEFAULT_END}.")
    ap.add_argument("--dates-file", type=Path, default=None,
                    help="Optional JSON list (or {regime:[iso]} dict) of UTC "
                         "timestamps; intersects with snapshot_meta status='ok' "
                         "in the window.")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    start = _coerce_utc(datetime.fromisoformat(args.start))
    end = _coerce_utc(datetime.fromisoformat(args.end))

    with psycopg.connect(PG_DSN) as conn:
        ok_ts = _fetch_ok_timestamps(conn, start, end)
        if args.dates_file:
            wanted = set(_load_dates_file(args.dates_file))
            ok_ts = [t for t in ok_ts if t in wanted]
        if not ok_ts:
            raise SystemExit(f"no ok snapshots in {start}..{end}")

        hub_centroids = pd.read_csv(HUB_CENTROIDS_CSV).set_index("settlement_point")
        bus_xy = pd.read_csv(
            NETWORK_BUS_COORDS_CSV, usecols=["bus", "lat", "lon"]
        ).dropna(subset=["lat", "lon"]).drop_duplicates(subset=["bus"])
        bus_coords_full = bus_xy[["lat", "lon"]].to_numpy()
        bus_ids_full = bus_xy["bus"].astype(str).to_numpy()
        k_max = max(K_VALUES)
        knn_top = _hub_knn_indices(bus_coords_full, bus_ids_full, hub_centroids, k_max)

        ercot_by_hub = _fetch_ercot_hub_spp(conn, ok_ts)
        model_by_k = _stream_model_hub_means(conn, ok_ts, knn_top)

    n_matched = len(ok_ts)
    print(f"matched snapshots: {n_matched}")

    aggregate_ratios: dict[int, list[float]] = {k: [] for k in K_VALUES}
    aggregate_spikes: dict[int, int] = {k: 0 for k in K_VALUES}
    aggregate_neg: dict[int, int] = {k: 0 for k in K_VALUES}

    hub_tables: list[str] = []
    for hub in HUBS:
        ercot_series = pd.Series(ercot_by_hub.get(hub, {}), dtype=float)
        if ercot_series.empty:
            continue
        per_k = {}
        for k in K_VALUES:
            model_series = pd.Series(model_by_k[k].get(hub, {}), dtype=float)
            per_k[k] = _stats(model_series, ercot_series)
            if per_k[k]["n"] > 0:
                aggregate_ratios[k].append(per_k[k]["median_ratio"])
                aggregate_spikes[k] += per_k[k]["n_spike"]
                aggregate_neg[k] += per_k[k]["n_negative"]
        hub_tables.append(_hub_table_md(hub, per_k))

    aggregate_drift: dict[int, float] = {}
    for k in K_VALUES:
        ratios = [r for r in aggregate_ratios[k] if pd.notna(r)]
        aggregate_drift[k] = (
            float(np.mean([abs(1.0 - r) for r in ratios])) if ratios else float("nan")
        )

    picked_k, rationale = _pick_k(aggregate_drift, aggregate_spikes, aggregate_neg)
    print(f"recommended k={picked_k}")

    md_lines: list[str] = [
        "# Hub LMP k-nearest sweep",
        "",
        "## Recommended k",
        "",
        f"**k = {picked_k}** — {rationale}.",
        "",
        f"* mean(|1 − med_ratio|) = {_fmt(aggregate_drift[picked_k], '.3f')}",
        f"* total n_spike (|x| > {SPIKE_ABS:.0f}) = {aggregate_spikes[picked_k]}",
        f"* total n_neg = {aggregate_neg[picked_k]}",
        "",
        "Model `hub_avg` averages the k synthetic buses nearest each ERCOT hub "
        "centroid. This sweep reads per-bus LMPs directly from `bus_snapshots` "
        "and compares each k against the ERCOT DAM SPP for the same timestamps.",
        "",
        f"* Snapshots matched: {n_matched}",
        f"* Window: {start.isoformat()} .. {end.isoformat()}",
        "",
    ]
    md_lines.extend(hub_tables)

    md_lines.append("## Summary (across all hubs)\n")
    md_lines.append(
        "| k | mean(|1 - med_ratio|) | total n_spike | total n_neg |\n"
        "|---:|---:|---:|---:|"
    )
    for k in K_VALUES:
        md_lines.append(
            f"| {k} | {_fmt(aggregate_drift[k], '.3f')} | {aggregate_spikes[k]} | "
            f"{aggregate_neg[k]} |"
        )
    md_lines.append("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(md_lines))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
