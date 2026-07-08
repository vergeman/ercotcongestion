#
from __future__ import annotations

import os


class Settings:
    # ---- Project ----------------------------------------------------------
    case_stem: str = os.environ.get('CASE_STEM', 'Texas2k_series25_case1_summerpeak')

    # ---- Paths (overridable; default to container conventions) -----------
    data_dir:      str = os.environ.get('DATA_DIR',      '/data/raw')
    processed_dir: str = os.environ.get('PROCESSED_DIR', '/data/processed')

    # ---- Database (required) ---------------------------------------------
    pg_host:     str = os.environ.get('PG_HOST', 'db')
    pg_port:     int = int(os.environ.get('PG_PORT', '5432'))
    pg_database: str = os.environ.get('PG_DATABASE', 'ercot')
    pg_user:     str = os.environ.get('PG_USER', 'postgres')
    pg_password: str = os.environ.get('PG_PASSWORD', 'abc123')

    # ---- Solver -----------------------------------------------------------
    # HiGHS thread count for batched OPF. >1 enables PAMI (parallel dual
    # simplex). Default 8 is tuned for a dev box; raise on beefier prod
    # machines via HIGHS_THREADS=<n>.
    highs_threads: int = int(os.environ.get('HIGHS_THREADS', '8'))

    # ---- API --------------------------------------------------------------
    frontend_origin:       str  = os.environ.get('FRONTEND_ORIGIN', 'http://localhost:5173')
    topology_cache:        str  = os.environ.get('TOPOLOGY_CACHE', '/data/processed/topology.json')
    min_validation_hour:   int  = int(os.environ.get('MIN_VALIDATION_HOUR', 24))
    max_state_range_hours: int  = int(os.environ.get('MAX_STATE_RANGE_HOURS', 24 * 14))

    # ---- Runs -------------------------------------------------------------
    # ``served_run_dir`` is the only knob the API reads. It is a symlink
    # managed by ``compute.promote`` — the API is oblivious to which run,
    # cell, or ref is live. Every artifact is opened at a fixed path
    # underneath (``mapping/scorecard.json``, ``clustering/cluster_labels.npz``,
    # ``matrix/congestion_matrices.npz``, ...) and the symlinks decide what
    # those paths resolve to.
    compute_runs_dir:      str  = os.environ.get('COMPUTE_RUNS_DIR', '/compute/runs')
    served_run_dir:        str  = os.environ.get('SERVED_RUN_DIR', '/compute/runs/current')

    # ---- Data Processed --------- -----------------------------------------
    network_nc                     = f'{processed_dir}/{case_stem}.nc'
    bus_weather_load_zones_csv     = f'{processed_dir}/bus_ercot_weather_load_zones.csv'
    generator_matches_csv          = f'{processed_dir}/generator_matches.csv'
    generator_matches_enriched_csv = f'{processed_dir}/generator_matches_enriched.csv'
    marginal_costs_csv             = f'{processed_dir}/marginal_costs.csv'
    master_eia860_csv              = f'{processed_dir}/master_eia860.csv'
    network_bus_coords_csv         = f'{processed_dir}/{case_stem}_bus_coords.csv'
    network_substations_csv        = f'{processed_dir}/{case_stem}_substations.csv'
    network_gen_fuels_csv          = f'{processed_dir}/{case_stem}_gen_fuels.csv'
    settlement_points_geocoded_csv = f'{processed_dir}/settlement_points_geocoded.csv'
    hubs_lz_centroids_csv          = f'{processed_dir}/hubs_lz_centroids.csv'

    # ---- Data Raw -------------- ------------------------------------------
    load_zones_geojson  = f'{data_dir}/ercot_load_zones/Load_Zones.geojson'
    weather_zones_shp   = f'{data_dir}/ercot_weather_zones/Weather_Zone.shp'
    tiger_shp           = f'{data_dir}/TIGER/tl_2024_us_county.shp'
    ercot_regions_xlsx  = f'{data_dir}/ercot_wind_solar_zones_counties/Wind and Solar Regions to County Mapping.xlsx'
    eia860_base_path    = f'{data_dir}/eia860/eia860'
    ercot_geocode_dir   = f'{data_dir}/ercot_geocode'
    ercot_geocode_review_queue_csv = f'{data_dir}/ercot_geocode/review_queue.csv'
    ercot_geocode_manual_overrides_csv = f'{data_dir}/ercot_geocode/manual_overrides.csv'

    # ---- Composite ------- -------------------------------------------------
    pg_dsn: str = (
        f"host={pg_host} port={pg_port} "
        f"dbname={pg_database} user={pg_user} "
        f"password={pg_password}"
    )

    @property
    def frontend_origins(self) -> list[str]:
        """Comma-separated FRONTEND_ORIGIN parsed into a list for CORS."""
        return [o.strip() for o in self.frontend_origin.split(',') if o.strip()]


# singleton
settings = Settings()
