-- 08_ercot_zonal_settlement.sql
--
-- ERCOT load zone LMPs from NP6-905-CD (Settlement Point Prices).
-- Filtered to the 4 load zone hubs: HB_NORTH, HB_HOUSTON, HB_SOUTH, HB_WEST.

CREATE TABLE IF NOT EXISTS ercot_zonal_lmp (
  interval_ts      TIMESTAMPTZ      NOT NULL,
  settlement_point TEXT             NOT NULL,   -- 'HB_NORTH', 'HB_HOUSTON', 'HB_SOUTH', 'HB_WEST'
  load_zone        TEXT             NOT NULL,   -- 'north', 'houston', 'south', 'west'
  lmp              DOUBLE PRECISION NOT NULL,
  dst_flag         BOOLEAN          NOT NULL DEFAULT FALSE,
  PRIMARY KEY (interval_ts, settlement_point)
);

-- Hypertable if using TimescaleDB:
SELECT create_hypertable('ercot_zonal_lmp', 'interval_ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_ercot_zonal_lmp_ts
  ON ercot_zonal_lmp (interval_ts);


-- Hourly mean view used by validation queries.
CREATE OR REPLACE VIEW ercot_zonal_lmp_hourly AS
SELECT
  date_trunc('hour', interval_ts) AS interval_ts,
  load_zone,
  AVG(lmp) AS lmp
  FROM ercot_zonal_lmp
GROUP BY date_trunc('hour', interval_ts), load_zone;

