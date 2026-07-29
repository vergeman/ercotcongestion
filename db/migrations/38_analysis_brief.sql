-- 38_analysis_brief.sql
--
-- The daily brief engine's output (plan/0124-filter-engine, docs/daily_brief_engine.md).
-- One JSON brief per (run_id, delivery_date, horizon): a deterministic re-ranking
-- of the day's forecast_sf_artifact into ranked constraints (F1) with node extrema
-- (F2) + shape stats (F3), nodal hotspots (F4), the hub/LZ dipole (F5a), plus a day
-- roll-up (daily ranks, peak hours, watchlist). Every number is a pure function of
-- the served artifact, so the brief is a materialized read-cache, not new data.
--
-- Keyed like forecast_sf_artifact (31, widened to include horizon in 37): the brief
-- is computed FROM one artifact horizon and shares its idempotency scope. A re-run of
-- daily_brief for a day replaces the blob in place (upsert on the PK); the compute
-- tick runs it right after daily_forecast publishes, and the F6 after-action fills in
-- the same row idempotently once DAM data lands.
--
-- brief is JSONB (not BYTEA) — it is a modest nested document the API serves verbatim,
-- so queryability and in-place read beat the artifact's compressed-blob trade-off.

CREATE TABLE IF NOT EXISTS analysis_brief (
  run_id        TEXT        NOT NULL,
  delivery_date DATE        NOT NULL,
  horizon       smallint    NOT NULL DEFAULT 1,
  brief         JSONB       NOT NULL,
  computed_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, delivery_date, horizon),
  CONSTRAINT analysis_brief_horizon_chk CHECK (horizon IN (1, 2))
);

-- The serving read slices by (run_id, delivery_date) and coalesces horizon, exactly
-- like the artifact lookup — covered by the PK's leading columns.
