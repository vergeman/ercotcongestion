-- 16_load_forecast.sql
--
-- NP3-561-CD: Seven-Day Load Forecast by Weather Zone.
-- Vintaged: posted_datetime is when the forecast was published; interval_ts is
-- the forecasted hour. ~24 publishes/day x 168 forecast hours each.

CREATE TABLE IF NOT EXISTS load_forecast_zonal (
  posted_datetime  TIMESTAMPTZ      NOT NULL,
  interval_ts      TIMESTAMPTZ      NOT NULL,
  delivery_date    DATE             NOT NULL,
  hour_ending      SMALLINT         NOT NULL,
  coast            DOUBLE PRECISION,
  east             DOUBLE PRECISION,
  far_west         DOUBLE PRECISION,
  north            DOUBLE PRECISION,
  north_central    DOUBLE PRECISION,
  south_central    DOUBLE PRECISION,
  southern         DOUBLE PRECISION,
  west             DOUBLE PRECISION,
  system_total     DOUBLE PRECISION,
  dst_flag         BOOLEAN          NOT NULL DEFAULT FALSE,
  PRIMARY KEY (posted_datetime, interval_ts, dst_flag)
);

SELECT create_hypertable('load_forecast_zonal', 'interval_ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_load_forecast_zonal_posted
  ON load_forecast_zonal (posted_datetime DESC, interval_ts);
