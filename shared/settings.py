#
from __future__ import annotations

import os
from pathlib import Path


class Settings:
    # ---- Project ----------------------------------------------------------
    case_stem: str = os.environ.get('CASE_STEM', 'Texas2k_series25_case1_summerpeak')

    # ---- Paths (overridable; default to container conventions) -----------
    data_dir:      Path = Path(os.environ.get('DATA_DIR',      '/data/raw'))
    processed_dir: Path = Path(os.environ.get('PROCESSED_DIR', '/data/processed'))

    # ---- Database (required) ---------------------------------------------
    pg_host:     str = os.environ.get('PG_HOST', 'db')
    pg_port:     int = int(os.environ.get('PG_PORT', '5432'))
    pg_database: str = os.environ.get('PG_DATABASE', 'ercot')
    pg_user:     str = os.environ.get('PG_USER', 'postgres')
    pg_password: str = os.environ.get('PG_PASSWORD', 'abc123')

    # ---- API --------------------------------------------------------------
    frontend_origin:       str  = os.environ.get('FRONTEND_ORIGIN', 'http://localhost:5173')
    topology_cache:        Path = Path(os.environ.get('TOPOLOGY_CACHE', '/data/processed/topology.json'))
    min_validation_hour:   int  = int(os.environ.get('MIN_VALIDATION_HOUR', 24))
    max_state_range_hours: int  = int(os.environ.get('MAX_STATE_RANGE_HOURS', 24 * 14))

    # ---- Data Processed --------- -----------------------------------------
    network_nc                     = processed_dir / f'{case_stem}.nc'
    bus_weather_load_zones_csv     = processed_dir / 'bus_ercot_weather_load_zones.csv'
    generator_matches_csv          = processed_dir / 'generator_matches.csv'
    generator_matches_enriched_csv = processed_dir / 'generator_matches_enriched.csv'
    marginal_costs_csv             = processed_dir / 'marginal_costs.csv'
    master_eia860_csv              = processed_dir / 'master_eia860.csv'
    network_bus_coords_csv         = processed_dir / f'{case_stem}_bus_coords.csv'
    network_substations_csv        = processed_dir / f'{case_stem}_substations.csv'
    network_gen_fuels_csv          = processed_dir / f'{case_stem}_gen_fuels.csv'

    # ---- Data Raw -------------- ------------------------------------------
    load_zones_geojson  = data_dir / 'ercot_load_zones/Load_Zones.geojson'
    weather_zones_shp   = data_dir / 'ercot_weather_zones/Weather_Zone.shp'
    tiger_shp           = data_dir / 'TIGER/tl_2024_us_county.shp'
    ercot_regions_xlsx  = data_dir / 'ercot_wind_solar_zones_counties/Wind and Solar Regions to County Mapping.xlsx'
    eia860_base_path    = data_dir / 'eia860/eia860'

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
