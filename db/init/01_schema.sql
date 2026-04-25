CREATE EXTENSION IF NOT EXISTS timescaledb;

-- SCED shadow prices: one row per (timestamp, constraint, contingency)
CREATE TABLE IF NOT EXISTS shadow_prices (
    sced_timestamp     TIMESTAMPTZ      NOT NULL,
    repeated_hour_flag BOOLEAN,
    constraint_id      INTEGER          NOT NULL,
    constraint_name    TEXT             NOT NULL,
    contingency_name   TEXT             NOT NULL,
    shadow_price       DOUBLE PRECISION,
    max_shadow_price   DOUBLE PRECISION,
    limit_mw           DOUBLE PRECISION,
    value_mw           DOUBLE PRECISION,
    violated_mw        DOUBLE PRECISION,
    from_station       TEXT,
    to_station         TEXT,
    from_kv            DOUBLE PRECISION,
    to_kv              DOUBLE PRECISION,
    cct_status         TEXT,
    PRIMARY KEY (sced_timestamp, constraint_id, contingency_name, repeated_hour_flag)
);

SELECT create_hypertable('shadow_prices', 'sced_timestamp', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_shadow_constraint ON shadow_prices (constraint_name, sced_timestamp DESC);

-- Outages: one row per (posted, operating_date, hour_ending)
CREATE TABLE IF NOT EXISTS outages_zonal (
    posted_datetime     TIMESTAMPTZ NOT NULL,
    operating_date      DATE        NOT NULL,
    hour_ending         SMALLINT    NOT NULL,
    total_mw_south      DOUBLE PRECISION,
    total_mw_north      DOUBLE PRECISION,
    total_mw_west       DOUBLE PRECISION,
    total_mw_houston    DOUBLE PRECISION,
    irr_mw_south        DOUBLE PRECISION,
    irr_mw_north        DOUBLE PRECISION,
    irr_mw_west         DOUBLE PRECISION,
    irr_mw_houston      DOUBLE PRECISION,
    new_equip_mw_south   DOUBLE PRECISION,
    new_equip_mw_north   DOUBLE PRECISION,
    new_equip_mw_west    DOUBLE PRECISION,
    new_equip_mw_houston DOUBLE PRECISION,
    PRIMARY KEY (posted_datetime, operating_date, hour_ending)
);

SELECT create_hypertable('outages_zonal', 'posted_datetime', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_outages_operating ON outages_zonal (operating_date, hour_ending);
