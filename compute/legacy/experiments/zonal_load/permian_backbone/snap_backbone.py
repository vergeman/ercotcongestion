"""
Snap real 765-kV substations to Texas2k buses by lat/lon, score plausibility,
emit a SEGMENTS list for pilot_backbone. No OPF.

    docker compose run --rm compute python \
       /compute/experiments/zonal_load/permian_backbone/snap_backbone.py
"""
"""

INFO:pypsa.network.io:New version 1.2.3 available! (Current: 1.2.0)
INFO:pypsa.network.io:Imported network 'Texas2k Series 25' has buses, generators, lines, loads, shunt_impedances, transformers
   station coord_conf   bus  snap_km      bus_zone     grade
Drill_Hole        med  1093     10.0      far_west plausible
 Sand_Lake       high 13304      6.5      far_west plausible
  Solstice       high 13181      3.5      far_west plausible
 Longshore        med  1065      4.6          west plausible
  Dinosaur        med  5317      9.3 north_central plausible
  Big_Hill       high  3024     12.5          west plausible
 Bell_East       high  5279      4.3 north_central plausible
    Howard        med  4174      2.3 south_central plausible

SEGMENTS (paste into pilot_backbone):
SEGMENTS = [
    ("5317", "1065"),  # Dinosaur->Longshore
    ("1065", "1093"),  # Longshore->Drill_Hole
    ("5279", "3024"),  # Bell_East->Big_Hill
    ("3024", "13304"),  # Big_Hill->Sand_Lake
    ("4174", "13181"),  # Howard->Solstice
]

>> any IMPLAUSIBLE or far snap = geography unreliable for that node
"""

import sys; sys.path.insert(0, '/compute')
import math, pandas as pd, pypsa
from config import NETWORK_NC, BUS_WEATHER_LOAD_ZONES_CSV

# (lat, lon) from CCN filings; conf = coord confidence
STATIONS = {
    "Drill_Hole":  (31.90, -102.95, "med"),   # Andrews/Winkler, Permian
    "Sand_Lake":   (31.50, -103.40, "high"),  # NE of Pecos, Ward Co
    "Solstice":    (30.90, -102.88, "high"),  # near Fort Stockton, Pecos Co
    "Longshore":   (32.10, -101.50, "med"),   # W of Forsan, Howard Co
    "Dinosaur":    (32.40,  -97.80, "med"),   # N of Glen Rose, Somervell Co
    "Big_Hill":    (30.96, -100.50, "high"),  # 13mi NE Eldorado, Schleicher Co
    "Bell_East":   (31.02,  -97.30, "high"),  # 5.5mi SE Temple, Bell Co
    "Howard":      (29.20,  -98.80, "med"),   # SW of San Antonio, Bexar/Medina
}
# map's station-to-station chain (each becomes its own line)
SEGMENTS = [
    ("Dinosaur","Longshore"), ("Longshore","Drill_Hole"),       # west import
    ("Bell_East","Big_Hill"), ("Big_Hill","Sand_Lake"),          # central import
    ("Howard","Solstice"),                                       # south import
]

def haversine_km(a_lat,a_lon,b_lat,b_lon):
    R=6371; p=math.pi/180
    dlat=(b_lat-a_lat)*p; dlon=(b_lon-a_lon)*p
    h=math.sin(dlat/2)**2+math.cos(a_lat*p)*math.cos(b_lat*p)*math.sin(dlon/2)**2
    return 2*R*math.asin(math.sqrt(h))

n = pypsa.Network(NETWORK_NC)
bz = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
bz['zone'] = bz['ercot_weather_zone'].astype(str).str.lower().str.replace(' ','_')
zone = dict(zip(bz['name'].astype(str), bz['zone']))

def snap(lat, lon):
    d = n.buses.apply(lambda r: haversine_km(lat,lon,r['y'],r['x']), axis=1)
    b = d.idxmin(); return b, round(d.loc[b],1)

def grade(km):
    return "plausible" if km<25 else "marginal" if km<60 else "IMPLAUSIBLE"

snapped={}
rows=[]
for name,(lat,lon,conf) in STATIONS.items():
    b,km = snap(lat,lon)
    snapped[name]=b
    rows.append({"station":name,"coord_conf":conf,"bus":b,
                 "snap_km":km,"bus_zone":zone.get(str(b),"?"),"grade":grade(km)})
df=pd.DataFrame(rows)
pd.set_option('display.width',160)
print(df.to_string(index=False))

print("\nSEGMENTS (paste into pilot_backbone):")
print("SEGMENTS = [")
for a,b in SEGMENTS:
    print(f'    ("{snapped[a]}", "{snapped[b]}"),  # {a}->{b}')
print("]")
print("\n>> any IMPLAUSIBLE or far snap = geography unreliable for that node")
