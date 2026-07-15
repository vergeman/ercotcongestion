-- 27_resource_outages.sql
--
-- NP1-346-ER: Unplanned Resource Outages. Unit-level GENERATION outages (not
-- transmission — see plan/0089). Each archived document is a D-4 SNAPSHOT: the
-- outages active on the third day before its posting date. `posted_date` IS the
-- vintage; the snapshot describes `posted_date - 3` (applied downstream, commit 3).
-- Backward-only, so legal to train and serve under the existing history_cutoff.
--
-- KEY: (posted_date, resource_unit_code, actual_outage_start), NOT
-- (posted_date, resource_unit_code). Unit codes are NOT unique within a snapshot —
-- one resource carries several concurrent outage events, each with its own start
-- (e.g. FRNYPP_ST10 appears 7x on the 2026-07-14 snapshot). Keying on the unit code
-- alone would silently drop 74 of 370 rows. Confirmed against the wire, not assumed.
--
-- Timestamps are stored UTC; the wire gives them naive ERCOT Central.

CREATE TABLE IF NOT EXISTS resource_outages (
  posted_date            DATE             NOT NULL,
  resource_unit_code     TEXT             NOT NULL,
  actual_outage_start    TIMESTAMPTZ      NOT NULL,
  resource_name          TEXT             NOT NULL,
  fuel_type              TEXT,
  outage_type            TEXT,
  available_mw_max       DOUBLE PRECISION,
  available_mw_during    DOUBLE PRECISION,
  effective_mw_reduction DOUBLE PRECISION,
  planned_end_date       TIMESTAMPTZ,
  actual_end_date        TIMESTAMPTZ,
  nature_of_work         TEXT,
  PRIMARY KEY (posted_date, resource_unit_code, actual_outage_start)
);

-- The covariate reads one vintage at a time (the newest posted_date admissible at
-- DAM close for a delivery day), so posted_date is the hot access path.
CREATE INDEX IF NOT EXISTS idx_resource_outages_posted
  ON resource_outages (posted_date);
