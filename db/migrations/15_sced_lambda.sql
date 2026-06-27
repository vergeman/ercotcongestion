-- 15_sced_lambda.sql
--
-- NP6-322-CD: SCED System Lambda. ~5-min grain (~288 rows/day).

CREATE TABLE IF NOT EXISTS sced_system_lambda (
  sced_timestamp     TIMESTAMPTZ      NOT NULL,
  repeated_hour_flag BOOLEAN          NOT NULL DEFAULT FALSE,
  system_lambda      DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (sced_timestamp, repeated_hour_flag)
);

SELECT create_hypertable('sced_system_lambda', 'sced_timestamp', if_not_exists => TRUE);
