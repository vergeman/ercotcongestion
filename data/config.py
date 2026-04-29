from pathlib import Path

# Network File
CASE_STEM = "Texas2k_series25_case1_summerpeak"
PROCESSED_DIR = Path("/data/processed")
NETWORK_NC = Path(f"{PROCESSED_DIR}/{CASE_STEM}.nc")

# Geo Lookup Sources and Authoritative Data
LOAD_ZONES_GEOJSON = Path('/data/ercot_load_zones/Load_Zones.geojson')
WEATHER_ZONES_SHP  = Path("/data/ercot_weather_zones/Weather_Zone.shp")
TIGER_SHP          = Path('/data/TIGER/tl_2024_us_county.shp')
ERCOT_REGIONS_XLSX = Path('/data/ercot_wind_solar_zones_counties/Wind and Solar Regions to County Mapping.xlsx')

#
# Processed Files
#

# extract_latlng_fuel.py
NETWORK_BUS_COORDS_CSV              = Path(f"{CASE_STEM}_bus_coords.csv")
NETWORK_SUBSTATIONS_CSV             = Path(f"{CASE_STEM}_substations.csv")
NETWORK_GEN_FUELS_CSV               = Path(f"{CASE_STEM}_gen_fuels.csv")


# extract_eia860.py
EIA860_BASE_PATH                    = Path("eia860/eia860")
MASTER_EIA860_CSV                   = Path(f"{PROCESSED_DIR}/master_eia860.csv")

# assign_bus_weather_load_zones.py
BUS_WEATHER_LOAD_ZONES_CSV          = Path(f"{PROCESSED_DIR}/bus_ercot_weather_load_zones.csv")

# match_generators.py, enrich_generators.py
GENERATOR_MATCHES_CSV               = Path(f"{PROCESSED_DIR}/generator_matches.csv")
GENERATOR_MATCHES_ENRICHED_CSV      = Path(f"{PROCESSED_DIR}/generator_matches_enriched.csv")

# marginal_costs.py
MARGINAL_COSTS_CSV                  = Path(f"{PROCESSED_DIR}/marginal_costs.csv")
