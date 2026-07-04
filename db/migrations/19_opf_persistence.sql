-- 19_opf_persistence.sql
--
-- Persist every OPF-solve output the analytical pipeline needs downstream so a
-- single solve captures the full picture (no reliance on model_results.json.gz).
--
-- snapshot_meta gains per-ts scalars + JSONB caches:
--   system_lambda_kkt          — system λ from the KKT-consistent solve
--   system_lambda_merit_order  — system λ from the merit-order solve
--   load_shed_mw               — total load shed (MW) at the snapshot
--   hub_lmps                   — {"HB_NORTH": 42.13, ...} for all 4 hubs
--   reference_prices           — cached scalar refs per method
--
-- bus_snapshots gains:
--   dispatch                   — per-bus generator dispatch MW
--                                (sum over all gens at the bus; NULL if none)
--
-- Additive + IF NOT EXISTS → idempotent, safe to re-run.

ALTER TABLE snapshot_meta
    ADD COLUMN IF NOT EXISTS system_lambda_kkt         double precision,
    ADD COLUMN IF NOT EXISTS system_lambda_merit_order double precision,
    ADD COLUMN IF NOT EXISTS load_shed_mw              double precision,
    ADD COLUMN IF NOT EXISTS hub_lmps                  jsonb,
    ADD COLUMN IF NOT EXISTS reference_prices          jsonb;

ALTER TABLE bus_snapshots
    ADD COLUMN IF NOT EXISTS dispatch double precision;
