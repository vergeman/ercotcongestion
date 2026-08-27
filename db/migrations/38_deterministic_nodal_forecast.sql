-- Serve one deterministic nodal congestion forecast. Deploy deterministic readers
-- and writers with this migration. Historical ``point`` values are retained; do
-- not rewrite forecasts before applying it. Archive the old PVC prediction/band
-- files only after rollout verification, retaining walk-forward μ predictions for
-- offline evaluation.

ALTER TABLE forecast_nodal
  DROP COLUMN IF EXISTS p10,
  DROP COLUMN IF EXISTS p50,
  DROP COLUMN IF EXISTS p90;

ALTER TABLE scoreboard_weekly
  DROP COLUMN IF EXISTS coverage80,
  DROP COLUMN IF EXISTS band_width,
  DROP COLUMN IF EXISTS pinball;

ALTER TABLE scoreboard_daily
  DROP COLUMN IF EXISTS coverage80,
  DROP COLUMN IF EXISTS band_width,
  DROP COLUMN IF EXISTS pinball;
