-- Replace overloaded short comparison values with the owner-qualified IDs
-- consumed by the Scoreboard contract.  `source` remains the only identity
-- column, so the existing primary keys, rows, horizons, and metric values are
-- preserved exactly.
DO $$
DECLARE
  weekly_before bigint;
  daily_before bigint;
  retired_weekly bigint;
BEGIN
  SELECT count(*) INTO weekly_before FROM scoreboard_weekly;
  SELECT count(*) INTO daily_before FROM scoreboard_daily;

  -- `model_clim` was an 0188-retired diagnostic: p_bind × the former
  -- severity-head climatology. It has no canonical 0189 identity and cannot
  -- be renamed to `climatology`, which can share its primary key. Retire it
  -- explicitly; a second migration run simply deletes zero rows.
  DELETE FROM scoreboard_weekly WHERE source = 'model_clim';
  GET DIAGNOSTICS retired_weekly = ROW_COUNT;

  -- Refuse any other unknown source rather than silently losing or mislabeling
  -- a row. Canonical IDs are admitted to make reruns idempotent.
  IF EXISTS (
    SELECT 1 FROM scoreboard_weekly
    WHERE source NOT IN (
      'model', 'persistence', 'climatology', 'oracle', 'null',
      'scoreboard_model_backtest_nodal',
      'scoreboard_persistence_backtest_nodal',
      'scoreboard_climatology_backtest_nodal',
      'scoreboard_oracle_backtest_nodal', 'scoreboard_null_flat_nodal'
    )
  ) OR EXISTS (
    SELECT 1 FROM scoreboard_daily
    WHERE source NOT IN (
      'model', 'persistence', 'climatology', 'oracle', 'null',
      'scoreboard_model_served_nodal',
      'scoreboard_persistence_prior_day_nodal',
      'scoreboard_climatology_trailing_window_nodal',
      'scoreboard_oracle_settled_mu_nodal', 'scoreboard_null_flat_nodal'
    )
  ) THEN
    RAISE EXCEPTION 'unsupported Scoreboard comparison source; remove retired rows before 0189';
  END IF;

  UPDATE scoreboard_weekly
  SET source = CASE source
    WHEN 'model' THEN 'scoreboard_model_backtest_nodal'
    WHEN 'persistence' THEN 'scoreboard_persistence_backtest_nodal'
    WHEN 'climatology' THEN 'scoreboard_climatology_backtest_nodal'
    WHEN 'oracle' THEN 'scoreboard_oracle_backtest_nodal'
    WHEN 'null' THEN 'scoreboard_null_flat_nodal'
    ELSE source
  END
  WHERE source IN ('model', 'persistence', 'climatology', 'oracle', 'null');

  UPDATE scoreboard_daily
  SET source = CASE source
    WHEN 'model' THEN 'scoreboard_model_served_nodal'
    WHEN 'persistence' THEN 'scoreboard_persistence_prior_day_nodal'
    WHEN 'climatology' THEN 'scoreboard_climatology_trailing_window_nodal'
    WHEN 'oracle' THEN 'scoreboard_oracle_settled_mu_nodal'
    WHEN 'null' THEN 'scoreboard_null_flat_nodal'
    ELSE source
  END
  WHERE source IN ('model', 'persistence', 'climatology', 'oracle', 'null');

  IF (SELECT count(*) FROM scoreboard_weekly) <> weekly_before - retired_weekly
     OR (SELECT count(*) FROM scoreboard_daily) <> daily_before THEN
    RAISE EXCEPTION 'scoreboard comparison migration changed row counts';
  END IF;
END $$;
