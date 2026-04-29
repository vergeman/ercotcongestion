DROP TABLE IF EXISTS solar_hourly;

CREATE TABLE solar_hourly (
  delivery_date         DATE             NOT NULL,
  hour_ending           SMALLINT         NOT NULL,
  posted_datetime       TIMESTAMPTZ      NOT NULL,
  gen_system_wide       DOUBLE PRECISION,
  cop_hsl_system_wide   DOUBLE PRECISION,
  stppf_system_wide     DOUBLE PRECISION,
  pvgrpp_system_wide    DOUBLE PRECISION,
  hsl_system_wide       DOUBLE PRECISION,
  dst_flag              BOOLEAN,
  interval_ts           TIMESTAMPTZ      NOT NULL,
  PRIMARY KEY (interval_ts, dst_flag)
);
SELECT create_hypertable('solar_hourly', 'interval_ts', if_not_exists => TRUE);

