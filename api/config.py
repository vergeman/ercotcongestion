"""
API-specific config.
"""
from shared.settings import settings

# Re-export as module-level constants for any code still using the old style.
PG_DSN                          = settings.pg_dsn

FRONTEND_ORIGIN                 = settings.frontend_origin
TOPOLOGY_CACHE                  = settings.topology_cache

MIN_VALIDATION_HOURS = 24       # warn below this
MAX_STATE_RANGE_HOURS           = settings.max_state_range_hours

MAP_RUN_ID                      = settings.map_run_id
