-- 14_rt_lmp.sql
--
-- NP6-788-CD: RT LMPs at Settlement Points. ~5-min SCED grain.

CREATE TABLE IF NOT EXISTS ercot_rt_lmp (
  sced_timestamp     TIMESTAMPTZ      NOT NULL,
  repeated_hour_flag BOOLEAN          NOT NULL DEFAULT FALSE,
  settlement_point   TEXT             NOT NULL,
  lmp                DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (sced_timestamp, settlement_point, repeated_hour_flag)
);

SELECT create_hypertable('ercot_rt_lmp', 'sced_timestamp', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_ercot_rt_lmp_sp_ts
  ON ercot_rt_lmp (settlement_point, sced_timestamp DESC);
