-- 30_forecast_nodal.sql
--
-- The served nodal forecast panel (plan/0090 Phase 2, spec-phase2a-nodal-panel §6).
-- propagate.py already computes the per-SP P10/P50/P90 + deterministic point
-- forecast each window and discards it; 0009 tees it to a flat npz and this table
-- is where that panel lands for serving. The API resolves the forecast_current
-- pointer per request, the same DB-pointer-resolved-on-read pattern the IBP map
-- already uses — but this feature owns its own table + pointer (no dependency on
-- the legacy symlink / compute.promote path).
--
-- Backtest bulk (npz -> COPY) and production single-day writes (0011 / phase2b)
-- converge on this one table so the Phase-4 historic slider serves from the same
-- endpoint as tomorrow's forecast.
--
-- delivery_date is the ERCOT operating day (America/Chicago local date of ts); it
-- is the idempotency scope for a re-run (delete-then-copy per (run_id,
-- delivery_date)) and how production writes a single day. `point` is the model's
-- deterministic expectation E[mu]*SF and is stored alongside the sampling median
-- p50 because they differ (§4). p10/p50/p90/point are nullable — a NaN percentile
-- lands as NULL rather than dropping the row.
--
-- The per-SP sf_r2 (fit confidence) rides the existing IBP diagnostics, not this
-- table (§6). forecast_sf_artifact (the per-day SF + E_mu blob powering drivers /
-- what-if on demand) is NOT created here — it ships in 0011.

CREATE TABLE IF NOT EXISTS forecast_nodal (
  run_id           TEXT        NOT NULL,
  delivery_date    DATE        NOT NULL,
  ts               TIMESTAMPTZ NOT NULL,
  settlement_point TEXT        NOT NULL,
  p10              REAL,
  p50              REAL,   -- sampling median of the draws
  p90              REAL,
  point            REAL,   -- deterministic E[mu]*SF (§4); distinct from p50
  PRIMARY KEY (run_id, ts, settlement_point)
);

-- The delete-then-copy re-run and the day-scoped serving read both slice by
-- (run_id, delivery_date).
CREATE INDEX IF NOT EXISTS idx_forecast_nodal_run_date
  ON forecast_nodal (run_id, delivery_date);

-- Pointer table: which run_id is "current" for each forecast layer. One row per
-- layer (currently just 'ercot'). Promotion flips this pointer in a single
-- upsert, after the rows land; no redeploy. This is THIS feature's pointer, not
-- the legacy implied_binding_proximity_current.
CREATE TABLE IF NOT EXISTS forecast_current (
  layer        TEXT        PRIMARY KEY,   -- 'ercot'
  run_id       TEXT        NOT NULL,
  promoted_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
