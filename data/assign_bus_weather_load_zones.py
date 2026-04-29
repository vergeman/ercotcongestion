# /data/assign_weather_zones.py
import logging
from pathlib import Path
import pandas as pd
import geopandas as gpd
import pypsa

log = logging.getLogger(__name__)

WEATHER_ZONES_PATH  = Path("/data/ercot_weather_zones/Weather_Zone.shp")
NETWORK_PATH = Path("/data/processed/Texas2k_series25_case1_summerpeak.nc")
BUS_ZONES_OUTPUT_PATH  = Path("/data/processed/bus_ercot_weather_load_zones.csv")
LOAD_ZONES_GEOJSON = Path('ercot_load_zones/Load_Zones.geojson')

ERCOT_WEATHER_ZONE_CANONICAL = {
    'South': 'Southern',  # ERCOT uses 'Southern', not 'South'
    # Other zones already match ERCOT canonical names
}

LOAD_ZONE_CANONICAL: dict[str, str] = {
    # load zone GeoJSON's: add normalizations here if the source uses
    # 'LZ_NORTH', 'HOUSTON' caps, etc.
}


def load_zones(path=WEATHER_ZONES_PATH):
    """loads shapefile into a GeoDataFrame (geopandas)
    NB: quietly reads .dbf, .shx, .prj
    """
    return gpd.read_file(path)  # already EPSG:4326


def build_bus_gdf(n):
    """Convert PyPSA Network buses to GeoDataFrame of points."""
    buses = n.buses[['x', 'y']].copy().rename(columns={'x': 'lon', 'y': 'lat'})
    buses.index.name = 'name'

    return gpd.GeoDataFrame(
        buses.reset_index(),
        geometry=gpd.points_from_xy(buses['lon'], buses['lat']),
        crs="EPSG:4326"
    )


def assign_zone(
        buses_gdf: gpd.GeoDataFrame,
        zones_gdf: gpd.GeoDataFrame,
        zone_col: str,
        output_col: str,
        canonical: dict[str, str] | None = None,
) -> pd.Series:
    """Assign each bus to the polygon containing it; fall back to nearest.

    Parameters
    ----------
    buses_gdf : points (EPSG:4326)
    zones_gdf : polygons (EPSG:4326). Must have `zone_col` and `geometry`.
    zone_col  : name of the zone-name column in zones_gdf (e.g. 'Zone_name', 'NAME')
    output_col: name to use for the result series
    canonical : optional name-normalization map applied after the join

    Returns
    -------
    pd.Series indexed like buses_gdf, named output_col, dtype object.
    """
    zones_subset = zones_gdf[[zone_col, 'geometry']]

    joined = gpd.sjoin(
        buses_gdf,
        zones_subset,
        how='left',
        predicate='within',
    )

    # Some buses may match multiple polygons due to overlapping/touching edges;
    # sjoin produces duplicate rows in that case. Keep first match per bus.
    if joined.index.has_duplicates:
        joined = joined[~joined.index.duplicated(keep='first')]

    unmatched_mask = joined[zone_col].isna()
    if unmatched_mask.any():
        n_unmatched = int(unmatched_mask.sum())
        log.info(f"  {n_unmatched} buses outside {output_col} polygons — using nearest")

        # Reproject both to a metric CRS for distances in meters.
        buses_proj = buses_gdf.to_crs(epsg=3083)   # Texas Albers
        zones_proj = zones_gdf.to_crs(epsg=3083)

        for idx in joined[unmatched_mask].index:
            pt = buses_proj.loc[idx, 'geometry']
            nearest = zones_proj.distance(pt).idxmin()
            joined.loc[idx, zone_col] = zones_gdf.loc[nearest, zone_col]

    if canonical:
        joined[zone_col] = joined[zone_col].replace(canonical)

    return joined[zone_col].rename(output_col)




if __name__ == '__main__':

    log.info(f"Loading network from {NETWORK_PATH}")
    n = pypsa.Network(NETWORK_PATH)
    buses_gdf = build_bus_gdf(n)
    log.info(f"  {len(buses_gdf)} buses")

    # ---- Weather zones ----
    log.info(f"Loading weather zones from {WEATHER_ZONES_PATH}")
    weather_zones = gpd.read_file(WEATHER_ZONES_PATH).to_crs('EPSG:4326')
    log.info(f"  {len(weather_zones)} weather zone polygons: "
             f"{sorted(weather_zones['Zone_name'].unique().tolist())}")
    weather_assigned = assign_zone(
        buses_gdf,
        weather_zones,
        zone_col='Zone_name',
        output_col='ercot_weather_zone',
        canonical=ERCOT_WEATHER_ZONE_CANONICAL,
    )

    # ---- Load zones ----
    log.info(f"Loading load zones from {LOAD_ZONES_GEOJSON}")
    load_zones = gpd.read_file(LOAD_ZONES_GEOJSON).to_crs('EPSG:4326')
    # Normalize NAME to lowercase up front; matches the convention used in
    # enrich_generators.py before this refactor consolidated the lookup here.
    load_zones['NAME'] = load_zones['NAME'].str.lower()
    log.info(f"  {len(load_zones)} load zone polygons: "
             f"{sorted(load_zones['NAME'].unique().tolist())}")
    load_assigned = assign_zone(
        buses_gdf,
        load_zones,
        zone_col='NAME',
        output_col='ercot_load_zone',
        canonical=LOAD_ZONE_CANONICAL or None,
    )

    out = (
        buses_gdf[['name', 'lat', 'lon']]
        .copy()
        .assign(
            ercot_weather_zone=weather_assigned.values,
            ercot_load_zone=load_assigned.values,
        )
    )


    # Sanity checks
    n_missing_w = out['ercot_weather_zone'].isna().sum()
    n_missing_l = out['ercot_load_zone'].isna().sum()
    if n_missing_w or n_missing_l:
        log.warning(
            f"Missing zone after fallback: weather={n_missing_w} load={n_missing_l}. "
            f"Investigate before downstream use."
        )

    log.info("Distribution by weather_zone:")
    for z, n_buses in out['ercot_weather_zone'].value_counts().items():
        log.info(f"  {z:20s} {n_buses}")

    log.info("Distribution by load_zone:")
    for z, n_buses in out['ercot_load_zone'].value_counts().items():
        log.info(f"  {z:20s} {n_buses}")

    out.to_csv(BUS_ZONES_OUTPUT_PATH, index=False)
    log.info(f"Wrote {BUS_ZONES_OUTPUT_PATH} ({len(out)} buses)")
