# /data/assign_weather_zones.py
from pathlib import Path
import pandas as pd
import geopandas as gpd
import pypsa

ZONES_PATH  = Path("/data/ercot_zones/Weather_Zone.shp")
NETWORK_PATH = Path("/data/processed/Texas2k_series25_case1_summerpeak.nc")
OUTPUT_PATH  = Path("/data/processed/bus_zones.csv")


def load_zones(path=ZONES_PATH):
    """loads shapefile into a GeoDataFrame (geopandas)
    NB: quietly reads .dbf, .shx, .prj
    """
    return gpd.read_file(path)  # already EPSG:4326


def build_bus_gdf(n):
    """Convert PyPSA Network buses to GeoDataFrame of points."""
    buses = n.buses[['x', 'y']].copy().rename(columns={'x': 'lon', 'y': 'lat'})

    return gpd.GeoDataFrame(
        buses,
        geometry=gpd.points_from_xy(buses['lon'], buses['lat']),
        crs="EPSG:4326"
    )


def assign_zones(buses_gdf, zones_gdf, zone_col='Zone_name'):
    """Given buses from network, and zones from shapefile, find if the lat/lon of
    each bus point falls inside one of the zone's polygons. 'within' tests if
    exists. Adds "Zone_name" to buses.

    Any unmatched don't land inside polygon; fall back to nearest zone: pick
    zone of nearest polygon edge

    """
    joined = gpd.sjoin(
        buses_gdf,
        zones_gdf[[zone_col, 'geometry']],
        how='left',
        predicate='within'
    )

    unmatched_mask = joined[zone_col].isna()
    if unmatched_mask.any():
        print(f"  {unmatched_mask.sum()} buses outside polygons — using nearest zone")

        # Reproject to metric CRS for accurate distance calculation
        buses_proj  = buses_gdf.to_crs(epsg=3083)   # Texas Albers, meters
        zones_proj  = zones_gdf.to_crs(epsg=3083)

        # for all unmatched (NaN)
        for idx in joined[unmatched_mask].index:
            pt = buses_proj.loc[idx, 'geometry']
            nearest = zones_proj.distance(pt).idxmin() # calculates point to each zone, take min
            joined.loc[idx, zone_col] = zones_gdf.loc[nearest, zone_col] # lookup nearest zone and assign

    return joined[['lat', 'lon', zone_col]].rename(columns={zone_col: 'ercot_zone'})



if __name__ == '__main__':
    n = pypsa.Network(NETWORK_PATH)
    zones_gdf = load_zones()
    buses_gdf = build_bus_gdf(n)

    result = assign_zones(buses_gdf, zones_gdf)

    print(f"Buses: {len(result)}")
    print(f"Zone distribution:\n{result['ercot_zone'].value_counts()}")
    print(f"Unassigned: {result['ercot_zone'].isna().sum()}")

    result.to_csv(OUTPUT_PATH)
    print(f"Saved to {OUTPUT_PATH}")
