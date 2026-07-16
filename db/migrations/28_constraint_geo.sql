-- 28_constraint_geo.sql
--
-- Constraint geography for the SF map (plan/0090 Phase 1). geo.py maps each
-- opaque constraint key to its |SF|-weighted centroid + zone/kV mass, per honest
-- refit window (compute/mu/geo.py::constraint_geography). This table persists that
-- crosswalk so the /map/* endpoints can place a constraint in space without any
-- station-name matching (only 4.3% of binding mu-mass joins by name — R4).
--
-- Keyed by (run_id, window_start, constraint_key), mirroring implied_shift_factors:
-- one geography per constraint per refit. run_id identifies the (window, refit,
-- ridge, ...) fit that produced it; sweep runs stay off this table.
--
-- lat/lon/kv/zone_shares are honest NaN/NULL where a constraint's |SF| mass lands
-- entirely on settlement points we have no coordinates for — holes stay holes.
-- spread_km flags multimodality: a bimodal constraint's centroid can land between
-- its two lobes, so a large spread is a caution, not a location.

CREATE TABLE IF NOT EXISTS constraint_geo (
  run_id         TEXT        NOT NULL,
  window_start   TIMESTAMPTZ NOT NULL,
  constraint_key TEXT        NOT NULL,  -- constraint_name|contingency_name
  lat            REAL,
  lon            REAL,
  spread_km      REAL,                  -- |SF|-weighted RMS extent; large = multimodal caution
  kv_mean        REAL,
  kv_max         REAL,
  zone_shares    JSONB,                 -- {load_zone: |SF|-mass share}
  max_abs_sf     REAL,                  -- max_sp |SF|  (peak exposure; the stable summary, spec §6)
  binding_hours  INTEGER,               -- support in the fit window
  PRIMARY KEY (run_id, window_start, constraint_key)
);

-- The overlay layer reads the latest window for a run in one slice.
CREATE INDEX IF NOT EXISTS idx_constraint_geo_run_window
  ON constraint_geo (run_id, window_start);

-- Window-level SF stability (disjoint-adjacent-window SF correlation, the honest
-- ~0.47, from compute.sf.eval::_sf_corr). Nullable: backfilled after the fit, and
-- NULL for older runs that predate the map surface. Per-CONSTRAINT stability is
-- deferred (spec §1.3, §9) — this window-level number plus oos_r2/coverage is what
-- the explorer uses to label a refit's trustworthiness.
ALTER TABLE sf_window_meta ADD COLUMN IF NOT EXISTS sf_stability REAL;
