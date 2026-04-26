DROP TABLE IF EXISTS wind_hourly;

CREATE TABLE wind_hourly (
    delivery_date  DATE             NOT NULL,
    hour_ending    SMALLINT         NOT NULL,
    posted_datetime TIMESTAMPTZ     NOT NULL,
    -- System-wide
    gen_system_wide       DOUBLE PRECISION,
    cop_hsl_system_wide   DOUBLE PRECISION,
    stwpf_system_wide     DOUBLE PRECISION,
    wgrpp_system_wide     DOUBLE PRECISION,
    hsl_system_wide       DOUBLE PRECISION,
    -- Per zone: South Houston
    gen_lz_south_houston      DOUBLE PRECISION,
    cop_hsl_lz_south_houston  DOUBLE PRECISION,
    stwpf_lz_south_houston    DOUBLE PRECISION,
    wgrpp_lz_south_houston    DOUBLE PRECISION,
    -- Per zone: West
    gen_lz_west       DOUBLE PRECISION,
    cop_hsl_lz_west   DOUBLE PRECISION,
    stwpf_lz_west     DOUBLE PRECISION,
    wgrpp_lz_west     DOUBLE PRECISION,
    -- Per zone: North
    gen_lz_north      DOUBLE PRECISION,
    cop_hsl_lz_north  DOUBLE PRECISION,
    stwpf_lz_north    DOUBLE PRECISION,
    wgrpp_lz_north    DOUBLE PRECISION,
    dst_flag       BOOLEAN,
    interval_ts    TIMESTAMPTZ      NOT NULL,
    PRIMARY KEY (interval_ts, dst_flag)
);
SELECT create_hypertable('wind_hourly', 'interval_ts', if_not_exists => TRUE);
