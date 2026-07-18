-- 25_implied_shift_factors.sql
--
-- Persist the per-refit implied shift-factor matrix (SF) that rolling_sf
-- computes and, until now, discarded. metric.binding_proximity reduces SF to
-- the scalar bp = max_c |SF[c,sp]| (see 22_implied_binding_proximity.sql);
-- every v3 surface (node explorer, congestion = -Sum SF*mu_hat, coverage
-- decomposition, collinear grouping) needs the full signed matrix.
--
-- Like bp, SF is hyperparameter-sensitive: run_id identifies the
-- (window, refit, ridge, ...) combination that produced these rows. Sweep runs
-- stay on disk under runs/<run_id>/sf/; only rows written with --persist-sf
-- land here. See plan/S0b-persist-sf-matrix.md.
--
-- Storage note: dense-per-refit is ~400 constraints x 1,084 SPs x ~52 refits
-- ~= 22M rows/run. runner writes it threshold-sparsified (|sf| below
-- --sf-threshold dropped). After S2 (collinear grouping) the key becomes
-- groups x SPs, two orders smaller; constraint_key is left free-form TEXT so
-- that re-key needs no schema change.

CREATE TABLE IF NOT EXISTS implied_shift_factors (
  run_id           TEXT        NOT NULL,
  window_start     TIMESTAMPTZ NOT NULL,
  constraint_key   TEXT        NOT NULL,  -- constraint_name|contingency_name
  settlement_point TEXT        NOT NULL,
  sf               REAL        NOT NULL,
  PRIMARY KEY (run_id, window_start, constraint_key, settlement_point)
);

CREATE INDEX IF NOT EXISTS idx_implied_shift_factors_run_window
  ON implied_shift_factors (run_id, window_start);

-- One row per refit boundary: the window/score spans and the fit's support
-- counts. fit_r2 is the in-sample overall R^2 already emitted by
-- diagnostics.refit_diagnostics. oos_r2 and coverage are left NULL here for
-- S1 to backfill once the out-of-window eval is institutionalized.
CREATE TABLE IF NOT EXISTS sf_window_meta (
  run_id        TEXT        NOT NULL,
  window_start  TIMESTAMPTZ NOT NULL,
  window_end    TIMESTAMPTZ NOT NULL,
  score_start   TIMESTAMPTZ NOT NULL,
  score_end     TIMESTAMPTZ NOT NULL,
  n_kept        INTEGER     NOT NULL,
  n_dropped     INTEGER     NOT NULL,
  n_sf_clipped  INTEGER     NOT NULL,
  fit_r2        REAL,
  oos_r2        REAL,
  coverage      REAL,
  PRIMARY KEY (run_id, window_start)
);
