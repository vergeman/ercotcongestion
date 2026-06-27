-- 17_timestamp_correction.sql
--
-- Repair CT-as-UTC timestamp drift in raw-string columns. ERCOT returns
-- naive timestamp strings in Central Time; psycopg parsed them under the
-- UTC session TZ, mislabelling 11:55 CT as 11:55 UTC. The correct instant
-- is 5h (CDT) / 6h (CST) later.
--
-- Idempotent via the data_migrations sentinel: re-runs are no-ops.
--
-- DEPLOYMENT NOTE: apply this BEFORE the loader fix in loaders.py begins
-- producing correctly-localized rows, OR pause live_updater between deploy
-- and migration. Otherwise correctly-stored rows inserted after deploy will
-- be double-shifted into the future when this migration runs.
--
-- STRATEGY: For each affected table, stream rows through a temp table on
-- disk (CTAS), TRUNCATE the original, then re-INSERT with shifted values.
-- A single in-statement DELETE+INSERT CTE materialized whole tables in
-- memory and OOM-killed Postgres on shadow_prices; the staging-table
-- approach is bounded by disk, not by work_mem.
--
-- DST fall-back: PG's AT TIME ZONE 'America/Chicago' on the ambiguous
-- 01:00-01:59 CT hour (first Sunday of November) defaults to CST. Rows
-- whose dst/repeated-hour flag is FALSE represent the CDT-side first
-- occurrence and need a 1h pull-back. Handled inside _ercot_ct_to_utc().
-- outages_zonal has no DST flag, so fall-back-hour rows there are treated
-- as CST-side (default); 1h drift on a handful of November rows is the
-- accepted trade-off.
--
-- ON CONFLICT DO NOTHING on the re-insert handles pre-existing duplicates
-- spread across Timescale chunks (per-chunk PK enforcement can let dupes
-- in). One survivor per logical key is kept, matching loader semantics.

CREATE TABLE IF NOT EXISTS data_migrations (
  name        TEXT        PRIMARY KEY,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM data_migrations WHERE name = '17_timestamp_correction') THEN
    RAISE NOTICE '17_timestamp_correction already applied — skipping';
    RETURN;
  END IF;

  CREATE OR REPLACE FUNCTION _ercot_ct_to_utc(broken_ts timestamptz, dst_flag boolean)
  RETURNS timestamptz AS $f$
  DECLARE
    naive  timestamp   := broken_ts AT TIME ZONE 'UTC';
    result timestamptz := naive AT TIME ZONE 'America/Chicago';
  BEGIN
    IF dst_flag IS FALSE
       AND extract(month from naive) = 11
       AND extract(day   from naive) BETWEEN 1 AND 7
       AND extract(dow   from naive) = 0
       AND extract(hour  from naive) = 1
    THEN
      RETURN result - interval '1 hour';
    END IF;
    RETURN result;
  END;
  $f$ LANGUAGE plpgsql IMMUTABLE;

  -- shadow_prices
  CREATE TEMP TABLE _stage_shadow_prices ON COMMIT DROP AS
  SELECT _ercot_ct_to_utc(sced_timestamp, repeated_hour_flag) AS sced_timestamp,
         repeated_hour_flag, constraint_id, constraint_name,
         contingency_name, shadow_price, max_shadow_price, limit_mw, value_mw,
         violated_mw, from_station, to_station, from_kv, to_kv, cct_status
  FROM shadow_prices;
  TRUNCATE shadow_prices;
  INSERT INTO shadow_prices
    SELECT * FROM _stage_shadow_prices ON CONFLICT DO NOTHING;

  -- outages_zonal (no DST flag → NULL)
  CREATE TEMP TABLE _stage_outages_zonal ON COMMIT DROP AS
  SELECT _ercot_ct_to_utc(posted_datetime, NULL) AS posted_datetime,
         operating_date, hour_ending,
         total_mw_south, total_mw_north, total_mw_west, total_mw_houston,
         irr_mw_south, irr_mw_north, irr_mw_west, irr_mw_houston,
         new_equip_mw_south, new_equip_mw_north, new_equip_mw_west, new_equip_mw_houston
  FROM outages_zonal;
  TRUNCATE outages_zonal;
  INSERT INTO outages_zonal
    SELECT * FROM _stage_outages_zonal ON CONFLICT DO NOTHING;

  -- sced_system_lambda
  CREATE TEMP TABLE _stage_sced_system_lambda ON COMMIT DROP AS
  SELECT _ercot_ct_to_utc(sced_timestamp, repeated_hour_flag) AS sced_timestamp,
         repeated_hour_flag, system_lambda
  FROM sced_system_lambda;
  TRUNCATE sced_system_lambda;
  INSERT INTO sced_system_lambda
    SELECT * FROM _stage_sced_system_lambda ON CONFLICT DO NOTHING;

  -- ercot_rt_lmp
  CREATE TEMP TABLE _stage_ercot_rt_lmp ON COMMIT DROP AS
  SELECT _ercot_ct_to_utc(sced_timestamp, repeated_hour_flag) AS sced_timestamp,
         repeated_hour_flag, settlement_point, lmp
  FROM ercot_rt_lmp;
  TRUNCATE ercot_rt_lmp;
  INSERT INTO ercot_rt_lmp
    SELECT * FROM _stage_ercot_rt_lmp ON CONFLICT DO NOTHING;

  -- load_forecast_zonal
  CREATE TEMP TABLE _stage_load_forecast_zonal ON COMMIT DROP AS
  SELECT _ercot_ct_to_utc(posted_datetime, dst_flag) AS posted_datetime,
         interval_ts, delivery_date, hour_ending,
         coast, east, far_west, north, north_central, south_central,
         southern, west, system_total, dst_flag
  FROM load_forecast_zonal;
  TRUNCATE load_forecast_zonal;
  INSERT INTO load_forecast_zonal
    SELECT * FROM _stage_load_forecast_zonal ON CONFLICT DO NOTHING;

  -- wind/solar: posted_datetime isn't in PK and isn't the partition column,
  -- so a direct UPDATE is fine and avoids rewriting the whole table.
  UPDATE wind_hourly_regional
     SET posted_datetime = _ercot_ct_to_utc(posted_datetime, dst_flag);

  UPDATE solar_hourly_regional
     SET posted_datetime = _ercot_ct_to_utc(posted_datetime, dst_flag);

  DROP FUNCTION _ercot_ct_to_utc(timestamptz, boolean);

  INSERT INTO data_migrations (name) VALUES ('17_timestamp_correction');
END $$;
