"""Audit the bus -> ERCOT weather-zone assignment.

    docker compose run --rm compute python \
       /compute/experiments/zonal_load/model_baseline/zone_mapping_audit.py

Two outputs:
  1. Per-zone summary: bus count, load-bus count, total MW, system share.
  2. Geographic mislabel scan: for each LOAD bus, take its k nearest
     neighbors (great-circle) and majority-vote their weather zone. If a
     bus's assigned zone disagrees with its spatial neighborhood, flag it.
     A bus labeled 'north' but embedded among 'north_central' buses is the
     signature we're chasing (the far_west<->north allocation dipole).

The flagged-load total per (assigned -> neighborhood) pair tells you how much
load would move if the suspect buses were relabeled -- i.e. whether the north
over-allocation is a mapping slip vs a real synthetic-grid defect.
"""
import sys; sys.path.insert(0, '/compute')
import numpy as np, pandas as pd, pypsa
from config import NETWORK_NC, BUS_WEATHER_LOAD_ZONES_CSV, NETWORK_BUS_COORDS_CSV

K = 12  # neighbors for the majority vote

def pick(cols, *cands):
    low = {c.lower(): c for c in cols}
    for c in cands:
        if c in low: return low[c]
    raise KeyError(f"none of {cands} in {list(cols)}")

# --- load + merge: name, weather zone, coords, p_set ---
bz = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
bz['zone'] = bz['ercot_weather_zone'].astype(str).str.lower().str.replace(' ', '_')
bz['name'] = bz['name'].astype(str)

co = pd.read_csv(NETWORK_BUS_COORDS_CSV)
cn = pick(co.columns, 'name', 'bus', 'bus_id', 'bus_name')
clat = pick(co.columns, 'lat', 'latitude', 'y')
clon = pick(co.columns, 'lon', 'lng', 'long', 'longitude', 'x')
co = co.rename(columns={cn: 'name', clat: 'lat', clon: 'lon'})
co['name'] = co['name'].astype(str)

n = pypsa.Network(NETWORK_NC)
load_by_bus = n.loads.groupby('bus')['p_set'].sum()

df = (bz[['name', 'zone']]
      .merge(co[['name', 'lat', 'lon']], on='name', how='left'))
df['load_mw'] = df['name'].map(load_by_bus).fillna(0.0)

miss = df[['lat', 'lon']].isna().any(axis=1).sum()
if miss:
    print(f"[warn] {miss} buses missing coords (excluded from geo scan)")

# --- 1. per-zone summary ---
tot = df['load_mw'].sum()
summ = df.groupby('zone').agg(buses=('name', 'size'),
                              load_buses=('load_mw', lambda s: int((s > 0).sum())),
                              load_mw=('load_mw', 'sum'))
summ['share_pct'] = (100 * summ['load_mw'] / tot).round(1)
summ = summ.sort_values('load_mw', ascending=False)
print("\n=== per-zone summary ===")
print(summ.to_string())
print(f"TOTAL load {tot/1000:.1f} GW")

# --- 2. geographic mislabel scan (haversine kNN majority vote) ---
g = df.dropna(subset=['lat', 'lon']).reset_index(drop=True)
lat = np.radians(g['lat'].values); lon = np.radians(g['lon'].values)
# pairwise great-circle distance, brute force (n~2000 is fine)
dlat = lat[:, None] - lat[None, :]
dlon = lon[:, None] - lon[None, :]
a = np.sin(dlat/2)**2 + np.cos(lat)[:, None]*np.cos(lat)[None, :]*np.sin(dlon/2)**2
d = 6371.0 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))   # km
np.fill_diagonal(d, np.inf)

zones = g['zone'].values
nn = np.argsort(d, axis=1)[:, :K]
nbr_zone_mode = np.array([pd.Series(zones[row]).mode().iloc[0] for row in nn])

g['nbr_zone'] = nbr_zone_mode
flag = g[(g['zone'] != g['nbr_zone']) & (g['load_mw'] > 0)].copy()
print(f"\n=== mislabel scan: {len(flag)} load buses whose zone != {K}-NN neighborhood ===")
if len(flag):
    pair = (flag.groupby(['zone', 'nbr_zone'])
                .agg(buses=('name', 'size'), load_mw=('load_mw', 'sum'))
                .sort_values('load_mw', ascending=False))
    pair['load_mw'] = pair['load_mw'].round(0)
    print("assigned_zone -> neighborhood_zone  (load that would move if relabeled):")
    print(pair.to_string())
    print("\nTop suspect buses by load:")
    print(flag.sort_values('load_mw', ascending=False)
              .head(15)[['name', 'zone', 'nbr_zone', 'load_mw', 'lat', 'lon']]
              .to_string(index=False))
else:
    print("none — every load bus agrees with its spatial neighborhood.")
