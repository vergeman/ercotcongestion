-- 22_implied_binding_proximity.sql
--
-- Persist a promoted implied-binding-proximity (bp_ercot) run so the API can
-- serve it without reading npz off disk. bp_ercot is
-- hyperparameter-sensitive; run_id identifies the (window, refit, ridge, ...)
-- combination that produced these values.
--
-- Sweep runs stay on disk under runs/<run_id>/ibp/; only promoted runs land
-- here. See plan 0064.

CREATE TABLE IF NOT EXISTS implied_binding_proximity (
  ts               TIMESTAMPTZ NOT NULL,
  settlement_point TEXT        NOT NULL,
  bp               REAL        NOT NULL,
  run_id           TEXT        NOT NULL,
  PRIMARY KEY (run_id, ts, settlement_point)
);

CREATE INDEX IF NOT EXISTS idx_implied_binding_proximity_run_ts
  ON implied_binding_proximity (run_id, ts);

-- Pointer table: which run_id is "current" for each map layer. One row per
-- layer (currently just 'ercot'). Promotion flips this pointer in a single
-- UPDATE; no redeploy required.
CREATE TABLE IF NOT EXISTS implied_binding_proximity_current (
  layer        TEXT        PRIMARY KEY,
  run_id       TEXT        NOT NULL,
  promoted_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
