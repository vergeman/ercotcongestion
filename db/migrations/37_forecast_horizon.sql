-- 37_forecast_horizon.sql
--
-- The forecast horizon column (plan/0123-forecast-horizon-preview, commit 1).
--
-- Adds a t+2 "preview" run alongside the t+1 "final" run. Same model version
-- (run_id is unchanged — it scopes MODEL VERSION only, spec §4); horizon is a
-- property of the run instance, so it is a column, not a run_id suffix.
--
--   horizon 1 = final   (the noon t+1 run; verification-grade)
--   horizon 2 = preview  (the ~14:45 CT t+2 run; lands inside the decision window)
--
-- Preview (horizon 2) rows are immutable once written: the noon t+1 run persists
-- horizon 1 side by side and never touches horizon 2, so `final − preview` is a
-- preserved audit trail of overnight covariate-vintage revisions on an otherwise
-- identical model.
--
-- Uniqueness everywhere widens to include horizon. Existing rows backfill to
-- horizon 1 via the DEFAULT — no data rewrite, and every current query (which
-- never mentions horizon) reads back the horizon-1 rows exactly as before.
--
-- Forward-only. Adding a NOT NULL column with a constant DEFAULT is a metadata-
-- only change in modern Postgres; the PK swaps below rebuild each table's unique
-- index once.

-- forecast_nodal: two horizons share the same (ts, settlement_point) for a
-- delivery day, so horizon must join the primary key or they collide.
ALTER TABLE forecast_nodal
  ADD COLUMN IF NOT EXISTS horizon smallint NOT NULL DEFAULT 1;
ALTER TABLE forecast_nodal
  DROP CONSTRAINT IF EXISTS forecast_nodal_horizon_chk,
  ADD CONSTRAINT forecast_nodal_horizon_chk CHECK (horizon IN (1, 2));
ALTER TABLE forecast_nodal
  DROP CONSTRAINT forecast_nodal_pkey,
  ADD PRIMARY KEY (run_id, ts, settlement_point, horizon);

-- The delete-then-copy re-run and the day-scoped serving read now slice by
-- (run_id, delivery_date, horizon).
DROP INDEX IF EXISTS idx_forecast_nodal_run_date;
CREATE INDEX IF NOT EXISTS idx_forecast_nodal_run_date
  ON forecast_nodal (run_id, delivery_date, horizon);

-- forecast_sf_artifact: one blob per (run_id, delivery_date, horizon).
ALTER TABLE forecast_sf_artifact
  ADD COLUMN IF NOT EXISTS horizon smallint NOT NULL DEFAULT 1;
ALTER TABLE forecast_sf_artifact
  DROP CONSTRAINT IF EXISTS forecast_sf_artifact_horizon_chk,
  ADD CONSTRAINT forecast_sf_artifact_horizon_chk CHECK (horizon IN (1, 2));
ALTER TABLE forecast_sf_artifact
  DROP CONSTRAINT forecast_sf_artifact_pkey,
  ADD PRIMARY KEY (run_id, delivery_date, horizon);

-- scoreboard_daily: two independent scoreboard tracks per run_id, one per horizon.
ALTER TABLE scoreboard_daily
  ADD COLUMN IF NOT EXISTS horizon smallint NOT NULL DEFAULT 1;
ALTER TABLE scoreboard_daily
  DROP CONSTRAINT IF EXISTS scoreboard_daily_horizon_chk,
  ADD CONSTRAINT scoreboard_daily_horizon_chk CHECK (horizon IN (1, 2));
ALTER TABLE scoreboard_daily
  DROP CONSTRAINT scoreboard_daily_pkey,
  ADD PRIMARY KEY (run_id, delivery_date, source, horizon);

DROP INDEX IF EXISTS idx_scoreboard_daily_run_date;
CREATE INDEX IF NOT EXISTS idx_scoreboard_daily_run_date
  ON scoreboard_daily (run_id, delivery_date, horizon);
