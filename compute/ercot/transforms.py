"""
ERCOT-side transforms used by ``compute.matrix``.

Pure DB-read + transform layer over the persisted ERCOT ingest tables
(``ercot_dam_spp``, ``dam_system_lambda``, ``load_by_zone``) plus the geocoded
settlement-point / hub / weather-zone reference CSVs. No I/O beyond the passed
psycopg connection and the reference CSVs.
"""
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from compute.congestion.compute import (
    compute_congestion, congestion_diagnostics,
    CUSTOM_HUBS, HUB_BUSAVG,
)

HUB_CENTROIDS_CSV = Path("/data/processed/hubs_lz_centroids.csv")
SP_GEOCODED_CSV = Path("/data/processed/settlement_points_geocoded.csv")
BUS_WEATHER_LOAD_ZONES_CSV = Path("/data/processed/bus_ercot_weather_load_zones.csv")

# 8 ERCOT weather zones (load_by_zone column names).
WEATHER_ZONES = (
    'coast', 'east', 'far_west', 'north',
    'north_central', 'south_central', 'southern', 'west',
)


# ---------------------------------------------------------------------------
# Setup (once per run)
# ---------------------------------------------------------------------------

def load_tracked_sps() -> pd.DataFrame:
    """Union of geocoded nodal SPs + hub/LZ centroids. Columns:
    settlement_point (index), lat, lon, nameplate_mw."""
    sp = pd.read_csv(SP_GEOCODED_CSV)[
        ['settlement_point', 'lat', 'lon', 'matched_capacity_mw']
    ].rename(columns={'matched_capacity_mw': 'nameplate_mw'})
    hubs = pd.read_csv(HUB_CENTROIDS_CSV)[['settlement_point', 'lat', 'lon']]
    hubs['nameplate_mw'] = 0.0  # hubs/LZs are aggregation points, not generators

    combined = pd.concat([sp, hubs], ignore_index=True)
    combined['nameplate_mw'] = combined['nameplate_mw'].fillna(0.0)
    # Drop dup SPs (a hub could in principle appear in both files); keep first
    combined = combined.drop_duplicates(subset='settlement_point', keep='first')
    return combined.set_index('settlement_point')


def assign_weather_zones(tracked: pd.DataFrame) -> pd.Series:
    """For each tracked SP, nearest-bus lookup -> weather zone (one of
    WEATHER_ZONES). Pattern mirrors congestion_snapshot.build_hub_lmps."""
    bz = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    bz['ercot_weather_zone'] = (
        bz['ercot_weather_zone'].astype(str).str.lower().str.replace(' ', '_')
    )
    valid_bz = bz.dropna(subset=['lat', 'lon', 'ercot_weather_zone'])
    bus_coords = valid_bz[['lat', 'lon']].to_numpy()
    bus_zones = valid_bz['ercot_weather_zone'].to_numpy()

    sp_xy = tracked[['lat', 'lon']].dropna()
    out = pd.Series(index=tracked.index, dtype=object)
    for sp, (slat, slon) in sp_xy.iterrows():
        d2 = (bus_coords[:, 0] - slat) ** 2 + (bus_coords[:, 1] - slon) ** 2
        out.loc[sp] = bus_zones[int(np.argmin(d2))]
    return out


# 4-way ERCOT load zones — the ones ERCOT actually settles LMPs against.
# Aligned 1:1 with the 4 traditional trading hubs (HB_HOUSTON etc.).
# HB_PAN is a hub but has no separate load zone — Panhandle buses settle
# as LZ_NORTH.
LOAD_ZONES = ('houston', 'north', 'south', 'west')


def assign_load_zones(tracked: pd.DataFrame) -> pd.Series:
    """For each tracked SP, nearest-bus lookup -> 4-way ERCOT load zone
    (one of LOAD_ZONES). 4-way sibling of assign_weather_zones() used by
    the zone_local_spp method in matrix.py."""
    bz = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    bz['ercot_load_zone'] = (
        bz['ercot_load_zone'].astype(str).str.lower().str.strip()
    )
    valid_bz = bz.dropna(subset=['lat', 'lon', 'ercot_load_zone'])
    valid_bz = valid_bz[valid_bz['ercot_load_zone'].isin(LOAD_ZONES)]
    bus_coords = valid_bz[['lat', 'lon']].to_numpy()
    bus_zones = valid_bz['ercot_load_zone'].to_numpy()

    sp_xy = tracked[['lat', 'lon']].dropna()
    out = pd.Series(index=tracked.index, dtype=object)
    for sp, (slat, slon) in sp_xy.iterrows():
        d2 = (bus_coords[:, 0] - slat) ** 2 + (bus_coords[:, 1] - slon) ** 2
        out.loc[sp] = bus_zones[int(np.argmin(d2))]
    return out


# ---------------------------------------------------------------------------
# Batched DB queries (one round-trip per data source per chunk of timestamps)
# ---------------------------------------------------------------------------

def fetch_dam_spp_batch(
    conn,
    ts_list: list[datetime],
    sps: list[str],
) -> dict[datetime, pd.Series]:
    """SPP per (ts, tracked SP) across a batch of timestamps. DST: take the
    dst_flag=ASC row per (ts, sp) (mirrors operating_data_adapter)."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT ON (interval_ts, settlement_point)
               interval_ts, settlement_point, dam_spp
        FROM ercot_dam_spp
        WHERE interval_ts = ANY(%s) AND settlement_point = ANY(%s)
        ORDER BY interval_ts, settlement_point, dst_flag ASC
        """,
        (ts_list, sps),
    )
    by_ts: dict[datetime, dict[str, float]] = {}
    for ts, sp, v in cur.fetchall():
        by_ts.setdefault(ts, {})[sp] = float(v)
    return {
        ts: pd.Series(d, name='dam_spp') for ts, d in by_ts.items()
    }


def fetch_system_lambda_batch(
    conn,
    ts_list: list[datetime],
) -> dict[datetime, float]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT DISTINCT ON (interval_ts) interval_ts, system_lambda
        FROM dam_system_lambda
        WHERE interval_ts = ANY(%s)
        ORDER BY interval_ts, dst_flag ASC
        """,
        (ts_list,),
    )
    return {ts: float(v) for ts, v in cur.fetchall()}


def fetch_zone_loads_batch(
    conn,
    ts_list: list[datetime],
) -> dict[datetime, dict[str, float]]:
    """load_by_zone is 15-min so several rows can share an hour-ending
    timestamp; aggregate by averaging within the hour."""
    cols = ', '.join(f'AVG({z}) AS {z}' for z in WEATHER_ZONES)
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT interval_ts, {cols}
        FROM load_by_zone
        WHERE interval_ts = ANY(%s)
        GROUP BY interval_ts
        """,
        (ts_list,),
    )
    out: dict[datetime, dict[str, float]] = {}
    for row in cur.fetchall():
        ts = row[0]
        out[ts] = {
            z: (float(v) if v is not None else 0.0)
            for z, v in zip(WEATHER_ZONES, row[1:])
        }
    return out


# ---------------------------------------------------------------------------
# Per-record build
# ---------------------------------------------------------------------------

def build_hub_lmps(lmps: pd.Series) -> dict[str, float]:
    """Read off the hub SPP values from the dam_spp result. Hubs missing
    from this hour's data are simply absent from the dict."""
    out: dict[str, float] = {}
    for hub in (HUB_BUSAVG, *CUSTOM_HUBS):
        if hub in lmps.index and pd.notna(lmps[hub]):
            out[hub] = float(lmps[hub])
    return out


def build_sp_load_weights(
    lmps_index: pd.Index,
    sp_to_zone: pd.Series,
    zone_loads: dict[str, float],
    sps_per_zone: dict[str, int],
) -> pd.Series:
    """Per-SP load weight: zone_load / count(SPs in zone). Indexed to lmps."""
    weights = pd.Series(0.0, index=lmps_index)
    for sp in lmps_index:
        zone = sp_to_zone.get(sp)
        if zone is None or zone not in zone_loads:
            continue
        n = sps_per_zone.get(zone, 0)
        if n <= 0:
            continue
        weights[sp] = zone_loads[zone] / n
    return weights


def _stats(s: pd.Series) -> dict:
    s = s.dropna()
    if s.empty:
        return {}
    return {
        "mean": float(s.mean()),
        "std": float(s.std()),
        "min": float(s.min()),
        "p5": float(s.quantile(0.05)),
        "p50": float(s.quantile(0.50)),
        "p95": float(s.quantile(0.95)),
        "max": float(s.max()),
        "n": int(s.shape[0]),
    }


def _sanity(
    cong: pd.DataFrame,
    n_sp: int,
    n_sp_with_nameplate: int,
    hub_lmps: dict,
    extreme_threshold: float = 2000.0,
) -> dict:
    """Mirror of 0011 sanity block + ERCOT coverage flags.

    n_sp_with_nameplate: count of SPs with positive matched_capacity_mw used
    in the gen_weighted reference. SPs without nameplate still receive a
    gen_weighted congestion value (scalar subtraction), they just don't
    contribute their LMP to computing the scalar. Watch this number — if it
    drifts well below n_settlement_points the gen_weighted reference is
    being computed from a thin / potentially biased subset.
    """
    sm = cong.get("simple_mean")
    centered = (
        sm is not None
        and not sm.dropna().empty
        and abs(float(sm.mean())) < 1e-6
    )
    return {
        "simple_mean_centered": bool(centered),
        "abs_max": float(cong.abs().max().max()) if not cong.empty else 0.0,
        "n_extreme": int((cong.abs() > extreme_threshold).sum().sum())
                     if not cong.empty else 0,
        "n_settlement_points": int(n_sp),
        "n_sp_with_nameplate": int(n_sp_with_nameplate),
        "n_missing_hubs": int(
            len({HUB_BUSAVG, *CUSTOM_HUBS}) - len(hub_lmps)
        ),
    }


def post_process_one(
    lmps: pd.Series,
    system_lambda: float | None,
    zone_loads: dict[str, float],
    sp_to_zone: pd.Series,
    sps_per_zone: dict[str, int],
    nameplate: pd.Series,
) -> dict:
    """Build one per-record dict from pre-fetched batch inputs."""
    hub_lmps = build_hub_lmps(lmps)
    sp_load = build_sp_load_weights(
        lmps.index, sp_to_zone, zone_loads, sps_per_zone,
    )
    nameplate_aligned = nameplate.reindex(lmps.index).fillna(0.0)

    cong, refs = compute_congestion(
        lmps, hub_lmps,
        loads=sp_load,
        dispatch=nameplate_aligned,
        system_lambda=system_lambda,
    )
    congestion_diagnostics(cong)

    return {
        "status": "ok",
        "hub_lmps": hub_lmps,
        # Per-method scalar reference prices — see model-side notes.
        # On the ERCOT side `system_lambda` carries the real NP4-523-CD
        # value; `system_lambda_kkt` and `system_lambda_merit_order` are
        # always None (model-only estimators).
        "reference_prices": refs,
        "lmp_summary": _stats(lmps),
        "sanity": _sanity(
            cong,
            n_sp=len(lmps),
            n_sp_with_nameplate=int((nameplate_aligned > 0).sum()),
            hub_lmps=hub_lmps,
        ),
        "congestion": {
            m: cong[m].dropna().round(3).to_dict() for m in cong.columns
        },
        "data_source": "dam",
    }
