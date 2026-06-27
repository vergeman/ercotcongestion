-- 12_dam_spp.sql
--
-- NP4-190-CD: DAM Settlement Point Prices. Hourly grain.

CREATE TABLE IF NOT EXISTS ercot_dam_spp (
  interval_ts      TIMESTAMPTZ      NOT NULL,
  settlement_point TEXT             NOT NULL,
  dam_spp          DOUBLE PRECISION NOT NULL,
  dst_flag         BOOLEAN          NOT NULL DEFAULT FALSE,
  PRIMARY KEY (interval_ts, settlement_point, dst_flag)
);

SELECT create_hypertable('ercot_dam_spp', 'interval_ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_ercot_dam_spp_ts
  ON ercot_dam_spp (interval_ts);
