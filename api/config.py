"""
API-specific config.
"""
import os
from pathlib import Path

CASE_STEM = "Texas2k_series25_case1_summerpeak"
PROCESSED_DIR = Path(os.getenv("DATA_DIR", "/data/processed"))

NETWORK_NC                          = Path(f"{PROCESSED_DIR}/{CASE_STEM}.nc")
BUS_WEATHER_LOAD_ZONES_CSV          = Path(f"{PROCESSED_DIR}/bus_ercot_weather_load_zones.csv")
GENERATOR_MATCHES_ENRICHED_CSV      = Path(f"{PROCESSED_DIR}/generator_matches_enriched.csv")


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


FRONTEND_ORIGINS = os.environ.get('FRONTEND_ORIGIN', 'http://localhost:5173')
TOPOLOGY_CACHE = os.environ.get('TOPOLOGY_CACHE', 'static/topology.json')

# Validation endpoint guardrails
MIN_VALIDATION_HOURS = 24       # warn below this
MAX_STATE_RANGE_HOURS = 24 * 14  # cap state_range to two weeks
