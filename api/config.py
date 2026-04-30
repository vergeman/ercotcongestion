"""
API-specific config.
"""
from shared.settings import settings

# Re-export as module-level constants for any code still using the old style.
PG_DSN                          = settings.pg_dsn
NETWORK_NC                      = settings.network_nc
BUS_WEATHER_LOAD_ZONES_CSV      = settings.bus_weather_load_zones_csv
GENERATOR_MATCHES_ENRICHED_CSV  = settings.generator_matches_enriched_csv

FRONTEND_ORIGINS                = settings.frontend_origins
TOPOLOGY_CACHE                  = settings.topology_cache

MIN_VALIDATION_HOURS = 24       # warn below this
MAX_STATE_RANGE_HOURS           = settings.max_state_range_hours
