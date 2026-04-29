
-- NP6-345-CD: Actual System Load by Weather Zone (15-min)
CREATE TABLE IF NOT EXISTS load_by_zone (
    operating_day  DATE             NOT NULL,
    hour_ending    SMALLINT         NOT NULL,
    interval_id    SMALLINT         NOT NULL,  -- 1-4 for 15-min intervals
    coast          DOUBLE PRECISION,
    east           DOUBLE PRECISION,
    far_west       DOUBLE PRECISION,
    north          DOUBLE PRECISION,
    north_central  DOUBLE PRECISION,
    south_central  DOUBLE PRECISION,
    southern       DOUBLE PRECISION,
    west           DOUBLE PRECISION,
    total          DOUBLE PRECISION,
    dst_flag       BOOLEAN,
    interval_ts    TIMESTAMPTZ      NOT NULL,
    PRIMARY KEY (interval_ts, dst_flag)
);
SELECT create_hypertable('load_by_zone', 'interval_ts', if_not_exists => TRUE);

-- NP4-732-CD: Wind Power Production - Hourly Averaged Actual + Forecasted
CREATE TABLE IF NOT EXISTS wind_hourly (
    delivery_date              DATE             NOT NULL,
    hour_ending                SMALLINT         NOT NULL,
    actual_system_wide         DOUBLE PRECISION,
    cop_hsl_system_wide        DOUBLE PRECISION,
    stwpf_system_wide          DOUBLE PRECISION,  -- Short-term wind power forecast
    wgrpp_system_wide          DOUBLE PRECISION,  -- Wind gen resource pp forecast
    dst_flag                   BOOLEAN,
    interval_ts                TIMESTAMPTZ      NOT NULL,
    PRIMARY KEY (interval_ts, dst_flag)
);
SELECT create_hypertable('wind_hourly', 'interval_ts', if_not_exists => TRUE);

-- NP4-737-CD: Solar Power Production - Hourly Averaged Actual + Forecasted
CREATE TABLE IF NOT EXISTS solar_hourly (
    delivery_date              DATE             NOT NULL,
    hour_ending                SMALLINT         NOT NULL,
    actual_system_wide         DOUBLE PRECISION,
    cop_hsl_system_wide        DOUBLE PRECISION,
    stppf_system_wide          DOUBLE PRECISION,  -- Short-term solar power forecast
    pvgrpp_system_wide         DOUBLE PRECISION,  -- PV gen resource pp forecast
    dst_flag                   BOOLEAN,
    interval_ts                TIMESTAMPTZ      NOT NULL,
    PRIMARY KEY (interval_ts, dst_flag)
);
SELECT create_hypertable('solar_hourly', 'interval_ts', if_not_exists => TRUE);
