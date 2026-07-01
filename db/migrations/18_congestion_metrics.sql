-- 18_congestion_metrics.sql
--
-- Add columns for the new congestion metrics produced by compute/congestion:
--   modeled_congestion  — signed Σ PTDF·μ ($/MWh) per bus
--   binding_proximity   — loading fraction per bus (aggregated across lines)
-- and corresponding snapshot_meta aggregates.
--
-- Old fragility columns are retained (NULLed on new writes) until API/frontend
-- cutover in 2B/2C. Migration B will drop them.
--
-- Additive + IF NOT EXISTS → idempotent, no writer coordination needed.

ALTER TABLE bus_snapshots
    ADD COLUMN IF NOT EXISTS modeled_congestion double precision,
    ADD COLUMN IF NOT EXISTS binding_proximity  double precision;

CREATE INDEX IF NOT EXISTS bus_snapshots_modeled_congestion_idx
    ON bus_snapshots (modeled_congestion DESC NULLS LAST)
    WHERE modeled_congestion IS NOT NULL;

CREATE INDEX IF NOT EXISTS bus_snapshots_binding_proximity_idx
    ON bus_snapshots (binding_proximity DESC NULLS LAST)
    WHERE binding_proximity IS NOT NULL;

ALTER TABLE snapshot_meta
    ADD COLUMN IF NOT EXISTS modeled_congestion_total       double precision,
    ADD COLUMN IF NOT EXISTS modeled_congestion_abs_total   double precision,
    ADD COLUMN IF NOT EXISTS modeled_congestion_top10_share double precision,
    ADD COLUMN IF NOT EXISTS binding_proximity_max          double precision,
    ADD COLUMN IF NOT EXISTS binding_proximity_p95          double precision;
