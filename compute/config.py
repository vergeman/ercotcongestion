# config.py

import os
from pathlib import Path
"""App/pipeline config — thin re-export from shared.settings.

New code should `from shared.settings import settings` directly. This module
exists for backward compatibility with the old constants-based imports.
"""
from shared.settings import settings

# Re-export as module-level constants for any code still using the old style.
PG_DSN                          = settings.pg_dsn
CASE_STEM                       = settings.case_stem
PROCESSED_DIR                   = settings.processed_dir
DATA_DIR                        = settings.data_dir

NETWORK_NC                      = settings.network_nc
NETWORK_PATH                    = settings.network_nc  # alias used by older imports
BUS_WEATHER_LOAD_ZONES_CSV      = settings.bus_weather_load_zones_csv
GENERATOR_MATCHES_CSV           = settings.generator_matches_csv
GENERATOR_MATCHES_ENRICHED_CSV  = settings.generator_matches_enriched_csv
MARGINAL_COSTS_CSV              = settings.marginal_costs_csv
MASTER_EIA860_CSV               = settings.master_eia860_csv

NETWORK_BUS_COORDS_CSV          = settings.network_bus_coords_csv
NETWORK_SUBSTATIONS_CSV         = settings.network_substations_csv
NETWORK_GEN_FUELS_CSV           = settings.network_gen_fuels_csv

LOAD_ZONES_GEOJSON              = settings.load_zones_geojson
WEATHER_ZONES_SHP               = settings.weather_zones_shp
TIGER_SHP                       = settings.tiger_shp
ERCOT_REGIONS_XLSX              = settings.ercot_regions_xlsx
EIA860_BASE_PATH                = settings.eia860_base_path

HIGHS_THREADS                   = settings.highs_threads
