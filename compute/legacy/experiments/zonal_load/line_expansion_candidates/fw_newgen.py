"""
Check whether Series25 GenDispatch scenarios reference gen buses absent from
the base network — focus on far_west. If none are new, it's just dispatch
scenarios and the backbone-only pilot stands.

    docker compose run --rm compute python \
        /compute/experiments/zonal_load/line_expansion_candidates/fw_newgen.py \
        --gendispatch /data/raw/Texas2k_series25_case1_summerpeak/Expansion_Planning_Problem_Data/GenDispatch1.csv
"""
import sys; sys.path.insert(0, '/compute')
import argparse
import pandas as pd
import pypsa
from config import NETWORK_NC, BUS_WEATHER_LOAD_ZONES_CSV

ap = argparse.ArgumentParser(); ap.add_argument('--gendispatch', required=True)
args = ap.parse_args()

# row 0 is the "Gen" section label; real header is row 1
g = pd.read_csv(args.gendispatch, skiprows=1)
g.columns = [c.strip() for c in g.columns]          # 'Number of Bus','ID','GenMW'
g['bus'] = g['Number of Bus'].astype(str)

n = pypsa.Network(NETWORK_NC)
net_buses = set(n.buses.index.astype(str))
net_gen_buses = set(n.generators['bus'].astype(str))

bz = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
bz['zone'] = bz['ercot_weather_zone'].astype(str).str.lower().str.replace(' ', '_')
fw = set(bz.loc[bz['zone'] == 'far_west', 'name'].astype(str))

gd_buses = set(g['bus'])
new_to_net = gd_buses - net_buses                    # bus not in network at all
new_gen    = gd_buses - net_gen_buses                # bus exists but no base gen
fw_new     = (new_to_net | new_gen) & fw

print(f"GenDispatch gen-buses: {len(gd_buses)}")
print(f"  not in network:           {len(new_to_net)}")
print(f"  no base generator there:  {len(new_gen)}")
print(f"  of those, in far_west:    {len(fw_new)}  {sorted(fw_new)[:10]}")
fwmw = g.loc[g['bus'].isin(fw_new), 'GenMW'].sum()
print(f"  far_west new-gen dispatch this scenario: {fwmw:,.0f} MW")
print("\n>> far_west new gen ~0  -> backbone-only pilot stands")
print(">> material far_west new gen -> add 'backbone + new gen' second arm")
