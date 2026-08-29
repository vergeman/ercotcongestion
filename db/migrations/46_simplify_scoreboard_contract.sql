-- Keep only all-hours screening scores on the product scoreboard.

DELETE FROM scoreboard_weekly WHERE regime <> 'all';

ALTER TABLE scoreboard_weekly
  DROP CONSTRAINT scoreboard_weekly_pkey,
  DROP COLUMN regime,
  DROP COLUMN pooled_r2,
  DROP COLUMN mae,
  ADD PRIMARY KEY (run_id, week, source);

ALTER TABLE scoreboard_daily
  DROP COLUMN pooled_r2,
  DROP COLUMN mae;
