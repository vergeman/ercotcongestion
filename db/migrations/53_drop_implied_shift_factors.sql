-- Retire the relational SF backfill source after the canonical artifact cutover.
-- Apply only after two successful weekly refreshes, a consumer/provenance audit,
-- and a fresh checksum-verified off-host backup (plan/pending-implied-shift-factors.md).
-- Preserve sf_window_meta, sf_window_artifact, and constraint_geo.
-- DROP TABLE removes its indexes; the explicit index drop also handles a no-op rerun.

BEGIN;
SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM sf_window_meta m
    LEFT JOIN sf_window_artifact a USING (run_id, window_start)
    WHERE a.run_id IS NULL
  ) THEN
    RAISE EXCEPTION 'Cannot drop legacy SF store: weekly metadata lacks canonical artifacts';
  END IF;
END $$;

DROP TABLE IF EXISTS implied_shift_factors;
DROP INDEX IF EXISTS idx_implied_shift_factors_run_window;
COMMIT;
