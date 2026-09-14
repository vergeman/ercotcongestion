-- Canonical dense weekly SF matrices.  The artifact references its metadata
-- window; writers insert metadata first, then the payload in one transaction.
CREATE TABLE IF NOT EXISTS sf_window_artifact (
  run_id TEXT NOT NULL,
  window_start TIMESTAMPTZ NOT NULL,
  sf_npz BYTEA NOT NULL,
  codec_version SMALLINT NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, window_start),
  FOREIGN KEY (run_id, window_start)
    REFERENCES sf_window_meta (run_id, window_start) ON DELETE CASCADE
);

ALTER TABLE forecast_sf_artifact
  ADD COLUMN IF NOT EXISTS sf_map_run_id TEXT,
  ADD COLUMN IF NOT EXISTS sf_window_start TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS sf_window_end TIMESTAMPTZ;

ALTER TABLE forecast_sf_artifact
  DROP CONSTRAINT IF EXISTS forecast_sf_artifact_sf_provenance_chk,
  ADD CONSTRAINT forecast_sf_artifact_sf_provenance_chk CHECK (
    (sf_map_run_id IS NULL AND sf_window_start IS NULL AND sf_window_end IS NULL)
    OR
    (sf_map_run_id IS NOT NULL AND sf_window_start IS NOT NULL AND sf_window_end IS NOT NULL)
  );
