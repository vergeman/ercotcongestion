-- 13_dam_lambda.sql
--
-- NP4-523-CD: DAM System Lambda. Hourly grain (24 rows/day).
-- System-wide marginal price; used as the baseline for congestion = LMP - lambda.

CREATE TABLE IF NOT EXISTS dam_system_lambda (
  interval_ts    TIMESTAMPTZ      NOT NULL,
  system_lambda  DOUBLE PRECISION NOT NULL,
  dst_flag       BOOLEAN          NOT NULL DEFAULT FALSE,
  PRIMARY KEY (interval_ts, dst_flag)
);

SELECT create_hypertable('dam_system_lambda', 'interval_ts', if_not_exists => TRUE);
