-- 39_forecast_constraint_daily.sql
--
-- Queryable daily totals derived from the otherwise blob-only E_mu portion of
-- forecast_sf_artifact.  The key deliberately mirrors the artifact's complete
-- horizon-aware idempotency scope: a re-run replaces just that forecast day.

CREATE TABLE IF NOT EXISTS forecast_constraint_daily (
  run_id          TEXT NOT NULL,
  delivery_date   DATE NOT NULL,
  horizon         SMALLINT NOT NULL,
  constraint_key  TEXT NOT NULL,
  forecast_mu     DOUBLE PRECISION NOT NULL,
  binding_hours   SMALLINT NOT NULL,
  PRIMARY KEY (run_id, delivery_date, horizon, constraint_key),
  CONSTRAINT forecast_constraint_daily_horizon_chk CHECK (horizon IN (1, 2)),
  CONSTRAINT forecast_constraint_daily_binding_hours_chk
    CHECK (binding_hours BETWEEN 0 AND 24)
);

-- The hero's trailing-window reader starts with this run/horizon/date slice.
CREATE INDEX IF NOT EXISTS idx_forecast_constraint_daily_run_horizon_date
  ON forecast_constraint_daily (run_id, horizon, delivery_date);
