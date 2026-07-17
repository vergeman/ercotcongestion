-- 31_forecast_sf_artifact.sql
--
-- The per-day SF + point-μ (E_mu) artifact (plan/0090 Phase 2,
-- spec-phase2a-nodal-panel §4a, §6). Drivers ("top-K constraints around a node")
-- and what-if (`−μ·SF[c,:]`) both carry a per-request parameter no stored panel
-- can enumerate, so instead of materializing ~240k driver rows/day (~75M across
-- the backtest) we ship the day's fitted SF matrix and its E_mu vector and let the
-- server reconstruct slices on read: `contrib[k] = −E_mu[ts,k]·SF[k,sp]`.
--
-- sf_npz is a flat/vocab-coded npz blob (SF on a shared constraint-key vocab, SPs
-- on an SP vocab, E_mu on the same key vocab) — the same key_vocab+key_code idiom
-- forecast_nodal's panel uses, so the whole day is one compact object (single-digit
-- MB) rather than a per-node-hour row explosion.
--
-- Keyed by (run_id, delivery_date), same idempotency scope as forecast_nodal (0010):
-- a re-run replaces the day's blob in place. No forecast_drivers table — driver rows
-- are never stored (§0, §6). The consuming /forecast/drivers + /forecast/whatif
-- endpoints are Phase 2 serving, built on a separate branch; this table is only the
-- substrate.

CREATE TABLE IF NOT EXISTS forecast_sf_artifact (
  run_id        TEXT  NOT NULL,
  delivery_date DATE  NOT NULL,
  sf_npz        BYTEA NOT NULL,   -- flat/vocab-coded SF + E_mu for the day
  PRIMARY KEY (run_id, delivery_date)
);
