"""Extract the model's native (unscaled) load by ERCOT weather zone.

    docker compose run --rm compute python \
       /compute/experiments/zonal_load/model_baseline/zonal_load_baseline.py

Answers two things at once:
  1. Grand total -> which case vintage you actually loaded
     (~67 GW = 2016 base / Series24 Case1; >80 GW = Series25 2025-level).
  2. Per-zone totals + share -> where the synthetic between-zone allocation
     sits vs reality. far_west should read low on share; that's the mis-siting.

This reads p_set straight off the static network (no scaling, no DB), so it is
the baseline BEFORE _scale_loads touches anything.
"""
import sys; sys.path.insert(0, '/compute')
import pandas as pd, pypsa
from config import NETWORK_NC, BUS_WEATHER_LOAD_ZONES_CSV

n = pypsa.Network(NETWORK_NC)

# bus -> weather zone, same mapping the adapter/comparison scripts use
bz = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
bz['zone'] = bz['ercot_weather_zone'].astype(str).str.lower().str.replace(' ', '_')
bus2zone = dict(zip(bz['name'].astype(str), bz['zone']))

loads = n.loads[['bus', 'p_set']].copy()
loads['zone'] = loads['bus'].astype(str).map(bus2zone)

unmapped = loads['zone'].isna().sum()
if unmapped:
    print(f"[warn] {unmapped} loads have no weather-zone mapping (excluded from zonal sums)")

total = float(loads['p_set'].sum())
z = (loads.groupby('zone')['p_set'].sum().sort_values(ascending=False))
out = pd.DataFrame({'load_mw': z.round(0), 'share_pct': (100 * z / total).round(1)})

print(f"\nModel native load by weather zone  (n_loads={len(loads)})")
print(out.to_string())
print(f"\nTOTAL: {total/1000:.1f} GW")
print("  ~67 GW  -> 2016 base (original ACTIVSg2000 / Series24 Case 1)")
print("  >80 GW  -> Series25 2025-level")

# Optional: collapse to your 4 validation hubs for a direct ERCOT-demand diff
WZ_TO_HUB = {'far_west': 'west', 'west': 'west', 'north': 'north',
             'north_central': 'north', 'east': 'houston', 'coast': 'houston',
             'south_central': 'south', 'southern': 'south'}
loads['hub'] = loads['zone'].map(WZ_TO_HUB)
h = loads.groupby('hub')['p_set'].sum().round(0)
print(f"\nCollapsed to 4 hubs (MW):\n{h.to_string()}")
