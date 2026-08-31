-- Replace overloaded short comparison values with the owner-qualified IDs
-- consumed by the Scoreboard contract.  `source` remains the only identity
-- column, so the existing primary keys, rows, horizons, and metric values are
-- preserved exactly.
DO $$
DECLARE
  weekly_before bigint;
  daily_before bigint;
BEGIN
  SELECT count(*) INTO weekly_before FROM scoreboard_weekly;
  SELECT count(*) INTO daily_before FROM scoreboard_daily;

  -- `model_clim` was retired by 0188 and has no lossless 0189 identity: it
  -- cannot be folded into climatology because both rows can share a primary
  -- key. Refuse any such stale or unknown source rather than silently losing
  -- a row or claiming it has the wrong construction.
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

  IF (SELECT count(*) FROM scoreboard_weekly) <> weekly_before
     OR (SELECT count(*) FROM scoreboard_daily) <> daily_before THEN
    RAISE EXCEPTION 'scoreboard comparison migration changed row counts';
  END IF;
END $$;
