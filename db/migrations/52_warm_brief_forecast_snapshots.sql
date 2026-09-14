ALTER TABLE brief_daily_snapshot
  DROP CONSTRAINT IF EXISTS brief_daily_snapshot_horizon_check;

ALTER TABLE brief_daily_snapshot
  ADD CONSTRAINT brief_daily_snapshot_horizon_check CHECK (horizon IN (1, 2));

ALTER TABLE brief_daily_snapshot
  ADD COLUMN IF NOT EXISTS snapshot_state TEXT NOT NULL DEFAULT 'settled';

ALTER TABLE brief_daily_snapshot
  ADD CONSTRAINT brief_daily_snapshot_state_check
  CHECK (snapshot_state IN ('preview', 'forecast', 'settled'));
