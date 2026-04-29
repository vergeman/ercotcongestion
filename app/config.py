# config.py

import os
from pathlib import Path

#
# PATHS
#
DATA_DIR = Path(os.getenv("DATA_DIR", "/data/processed"))

NETWORK_PATH        = DATA_DIR / "Texas2k_series25_case1_summerpeak.nc"
MARGINAL_COSTS_PATH = DATA_DIR / "marginal_costs.csv"
BUS_WEATHER_ZONES_PATH      = DATA_DIR / "bus_weather_zones.csv"
GEN_ENRICHED_PATH   = DATA_DIR / "generator_matches_enriched.csv"

#
# DB
#
PG_DSN = (
    f"host={os.environ['PG_HOST']} "
    f"port={os.environ['PG_PORT']} "
    f"dbname={os.environ['PG_DATABASE']} "
    f"user={os.environ['PG_USER']} "
    f"password={os.environ['PG_PASSWORD']}"
)
