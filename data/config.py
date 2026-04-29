from pathlib import Path

# Network File
NETWORK_NC = Path("/data/processed/Texas2k_series25_case1_summerpeak.nc")

# Geo Lookup Sources and Authoritative Data
LOAD_ZONES_GEOJSON = Path('/data/ercot_load_zones/Load_Zones.geojson')
WEATHER_ZONES_SHP  = Path("/data/ercot_weather_zones/Weather_Zone.shp")
TIGER_SHP          = Path('/data/TIGER/tl_2024_us_county.shp')
ERCOT_REGIONS_XLSX = Path('/data/ercot_wind_solar_zones_counties/Wind and Solar Regions to County Mapping.xlsx')

#
# Processed Files
#

# extract_eia860.py
EIA860_BASE_PATH                    = Path("eia860/eia860")
MASTER_EIA860_CSV                   = Path("/data/processed/master_eia860.csv")

# assign_bus_weather_load_zones.py
BUS_WEATHER_LOAD_ZONES_CSV          = Path("/data/processed/bus_ercot_weather_load_zones.csv")

# match_generators.py, enrich_generators.py
GENERATOR_MATCHES_CSV               = Path('/data/processed/generator_matches.csv')
GENERATOR_MATCHES_ENRICHED_CSV      = Path('/data/processed/generator_matches_enriched.csv')

# marginal_costs.py
MARGINAL_COSTS_CSV                  = Path("/data/processed/marginal_costs.csv")
