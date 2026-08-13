-- 39_essp.sql
--
-- NP4-158-SG: DAM Electrically Similar Settlement Points.  ERCOT publishes a
-- pre-DAM study and a post-DAM final for the same delivery day, so both
-- vintages are retained.  GroupIndex is intentionally only an hourly label:
-- it is not a durable identity for a group's membership across delivery days.

CREATE TABLE IF NOT EXISTS ercot_essp (
  interval_ts      TIMESTAMPTZ NOT NULL,
  dst_flag         BOOLEAN     NOT NULL DEFAULT FALSE,
  settlement_point TEXT        NOT NULL,
  group_index      INT         NOT NULL,
  is_study         BOOLEAN     NOT NULL DEFAULT FALSE,
  updated_at       TIMESTAMPTZ,
  PRIMARY KEY (interval_ts, settlement_point, is_study, dst_flag)
);

SELECT create_hypertable('ercot_essp', 'interval_ts', if_not_exists => TRUE);

-- The brief and map retrieve every member of a group for a delivery hour.
CREATE INDEX IF NOT EXISTS idx_ercot_essp_ts_group
  ON ercot_essp (interval_ts, group_index);
