"""
Enrich TAMU generators with the zone tags

Adds four columns to generator_matches.csv:
  county      - via spatial join against Census TIGER county polygons
  ercot_load_zone   - via spatial join against ERCOT load zone polygons (4 zones)
  pv_region   - via county lookup against ERCOT XLSX (solar generators only)
  wind_region - via county lookup against ERCOT XLSX (wind generators only)

The existing 'eia_county' column from match_generators.py is preserved as a
diagnostic. TIGER's 'county' is the canonical source going forward.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import geopandas as gpd
from shared.settings import settings

TIGER_SHP=settings.tiger_shp
ERCOT_REGIONS_XLSX=settings.ercot_regions_xlsx
BUS_WEATHER_LOAD_ZONES_CSV=settings.bus_weather_load_zones_csv
GENERATOR_MATCHES_CSV=settings.generator_matches_csv
GENERATOR_MATCHES_ENRICHED_CSV=settings.generator_matches_enriched_csv


def normalize_county(s: pd.Series) -> pd.Series:
    """Normalize county names for join: uppercase, strip whitespace, no 'County' suffix."""
    return (
        s.astype(str)
         .str.upper()
         .str.replace(' COUNTY', '', regex=False)
         .str.strip()
    )


#
# Main
#

def main():

    print(f"Loading {GENERATOR_MATCHES_CSV}")
    gens = pd.read_csv(GENERATOR_MATCHES_CSV)
    n_in = len(gens)

    # Rename existing 'county' (from EIA matching) to 'eia_county' to preserve
    # it as a diagnostic. TIGER will provide the canonical 'county' below.
    if 'county' in gens.columns and 'eia_county' not in gens.columns:
        gens = gens.rename(columns={'county': 'eia_county'})

    # ---- 1. County via TIGER spatial join -----------------------------------
    print(f"Loading TIGER counties from {TIGER_SHP}")
    counties = gpd.read_file(TIGER_SHP)
    tx_counties = (
        counties[counties['STATEFP'] == '48']
        [['NAME', 'geometry']]
        .rename(columns={'NAME': 'county'})
        .to_crs('EPSG:4326')
    )
    print(f"  {len(tx_counties)} Texas counties loaded")

    gdf = gpd.GeoDataFrame(
        gens,
        geometry=gpd.points_from_xy(gens['lon'], gens['lat']),
        crs='EPSG:4326',
    )
    gdf = (
        gpd.sjoin(gdf, tx_counties, how='left', predicate='within')
        .drop(columns=['index_right'])
    )
    n_no_county = gdf['county'].isna().sum()
    print(f"  Generators without county: {n_no_county}/{n_in}")
    if n_no_county > 0:
        outside = gdf[gdf['county'].isna()][['bus', 'lat', 'lon', 'carrier']]
        print("  (likely lat/lon outside Texas)")
        print(outside.head(10).to_string(index=False))

    # ---- 2. Apply ercot_load_zone from previous lookup  ---------------

    print(f"Loading bus -> ercot_load_zone from {BUS_WEATHER_LOAD_ZONES_CSV}")
    bus_zones = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    if 'ercot_load_zone' not in bus_zones.columns:
        raise ValueError(
            f"{BUS_WEATHER_LOAD_ZONES_CSV} is missing 'ercot_load_zone' column. "
            f"Run scripts/assign_zones.py to regenerate it."
        )
    print(f"  Load zones: {sorted(bus_zones['ercot_load_zone'].dropna().unique().tolist())}")

    # gdf['bus'] holds the PyPSA bus name; bus_zones['name'] is the same key.
    gdf = gdf.merge(
        bus_zones[['name', 'ercot_load_zone']],
        left_on='bus',
        right_on='name',
        how='left',
    ).drop(columns=['name'])

    # Some TAMU generators are not in ERCOT:
    # North Texas Panhandle: Hemphill, Moore, Hutchinson counties are served by SPP
    # East Texas: Liberty, Jasper, Newton, Sabine near Louisiana served by SERC.
    # Rio Grande hydro straddles Mexico.
    #
    # TODO: remember to set 'non_ercot' generators p_max_pu / p_max_pu_ceiling to 0

    gdf['ercot_load_zone'] = gdf['ercot_load_zone'].fillna('non_ercot')

    n_no_lz = gdf['ercot_load_zone'].isna().sum()
    print(f"  Generators without ercot_load_zone: {n_no_lz}/{n_in}")

    # ---- 3. PV / wind region via ERCOT XLSX lookup --------------------------
    print(f"Loading ERCOT region XLSX from {ERCOT_REGIONS_XLSX}")
    solar_xlsx = pd.read_excel(ERCOT_REGIONS_XLSX, sheet_name='Solar Region to County')
    wind_xlsx  = pd.read_excel(ERCOT_REGIONS_XLSX, sheet_name='Wind Region to County')

    solar_xlsx = solar_xlsx.rename(columns={'Solar Region': 'pv_region'})
    wind_xlsx  = wind_xlsx.rename(columns={'Wind Region': 'wind_region'})

    solar_xlsx['county_key'] = normalize_county(solar_xlsx['County'])
    wind_xlsx['county_key']  = normalize_county(wind_xlsx['County'])
    gdf['county_key'] = normalize_county(gdf['county'])

    # PV region for solar generators only
    gdf = gdf.merge(
        solar_xlsx[['county_key', 'pv_region']],
        on='county_key', how='left',
    )
    gdf.loc[gdf['carrier'] != 'solar', 'pv_region'] = pd.NA

    # Wind region for wind generators only
    gdf = gdf.merge(
        wind_xlsx[['county_key', 'wind_region']],
        on='county_key', how='left',
    )
    gdf.loc[gdf['carrier'] != 'wind', 'wind_region'] = pd.NA

    n_solar = (gdf['carrier'] == 'solar').sum()
    n_solar_tagged = gdf.loc[gdf['carrier'] == 'solar', 'pv_region'].notna().sum()
    n_wind = (gdf['carrier'] == 'wind').sum()
    n_wind_tagged = gdf.loc[gdf['carrier'] == 'wind', 'wind_region'].notna().sum()
    print(f"  Solar generators with pv_region: {n_solar_tagged}/{n_solar}")
    print(f"  Wind generators with wind_region: {n_wind_tagged}/{n_wind}")

    # ---- 4. Diagnostic: TIGER vs EIA county agreement -----------------------
    #
    # TAMU model placed a generator near a real plant but possibly in the next
    # county over. EIA data has real plant in County A though TAMU's lat/lon is
    # in County B.
    #
    # Default to TIGER not EIA county data, since we're using TAMU lat/lng as
    # truth - use 'county' field

    if 'eia_county' in gdf.columns:
        both = gdf.dropna(subset=['county', 'eia_county'])
        agreement = (
            normalize_county(both['county']) == normalize_county(both['eia_county'])
        ).mean()
        print(f"  TIGER vs EIA county agreement: {agreement:.1%} "
              f"({len(both)} comparable rows)")

    # ---- 5. Save ------------------------------------------------------------
    out = pd.DataFrame(gdf.drop(columns=['geometry', 'county_key']))
    out.to_csv(GENERATOR_MATCHES_ENRICHED_CSV, index=False)
    print(f"\nWrote {len(out)} rows to {GENERATOR_MATCHES_ENRICHED_CSV}")
    print(f"Columns: {out.columns.tolist()}")


if __name__ == '__main__':
    main()
