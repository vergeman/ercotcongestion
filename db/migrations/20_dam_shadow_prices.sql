-- 20_dam_shadow_prices.sql
--
-- NP4-191-CD: DAM Binding/Active Constraint Shadow Prices. Hourly grain.
-- DAM/hourly counterpart to NP6-86-CD (SCED/5-min shadow prices).

CREATE TABLE IF NOT EXISTS ercot_dam_shadow_prices (
  interval_ts       TIMESTAMPTZ      NOT NULL,
  dst_flag          BOOLEAN          NOT NULL DEFAULT FALSE,
  constraint_id     INTEGER          NOT NULL,
  constraint_name   TEXT             NOT NULL,
  contingency_name  TEXT             NOT NULL,
  shadow_price      DOUBLE PRECISION,
  limit_mw          DOUBLE PRECISION,
  value_mw          DOUBLE PRECISION,
  violated_mw       DOUBLE PRECISION,
  from_station      TEXT,
  to_station        TEXT,
  from_kv           DOUBLE PRECISION,
  to_kv             DOUBLE PRECISION,
  PRIMARY KEY (interval_ts, constraint_id, contingency_name, dst_flag)
);

SELECT create_hypertable('ercot_dam_shadow_prices', 'interval_ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_ercot_dam_shadow_prices_ts
  ON ercot_dam_shadow_prices (interval_ts);

CREATE INDEX IF NOT EXISTS idx_ercot_dam_shadow_prices_constraint
  ON ercot_dam_shadow_prices (constraint_name, contingency_name);
