-- Keep only all-hours screening scores on the product scoreboard.

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'scoreboard_weekly' AND column_name = 'regime'
  ) THEN
    DELETE FROM scoreboard_weekly WHERE regime <> 'all';
  END IF;
END $$;

DO $$
BEGIN
  -- The old primary key includes `regime`; leave the replacement untouched
  -- when a development database has already applied this migration.
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'scoreboard_weekly' AND column_name = 'regime'
  ) THEN
    ALTER TABLE scoreboard_weekly DROP CONSTRAINT IF EXISTS scoreboard_weekly_pkey;
  END IF;
END $$;

ALTER TABLE scoreboard_weekly
  DROP COLUMN IF EXISTS regime,
  DROP COLUMN IF EXISTS pooled_r2,
  DROP COLUMN IF EXISTS mae;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'scoreboard_weekly'::regclass AND contype = 'p'
  ) THEN
    ALTER TABLE scoreboard_weekly
      ADD CONSTRAINT scoreboard_weekly_pkey PRIMARY KEY (run_id, week, source);
  END IF;
END $$;

ALTER TABLE scoreboard_daily
  DROP COLUMN IF EXISTS pooled_r2,
  DROP COLUMN IF EXISTS mae;
