-- 42_analysis_grade_daily.sql
--
-- The Brief's own constraint/node grade is deliberately not scoreboard_daily:
-- it uses the v6 detection, magnitude, and timing definitions.  Store a daily
-- snapshot so the Brief can show a real trailing track without recalculating a
-- 30-day full-artifact grade during an HTTP request.

CREATE TABLE IF NOT EXISTS analysis_grade_daily (
  run_id        TEXT NOT NULL,
  delivery_date DATE NOT NULL,
  horizon       SMALLINT NOT NULL,
  subject       TEXT NOT NULL CHECK (subject IN ('constraints', 'nodes')),
  model         JSONB NOT NULL,
  persistence   JSONB NOT NULL,
  computed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, delivery_date, horizon, subject),
  CONSTRAINT analysis_grade_daily_horizon_chk CHECK (horizon IN (1, 2))
);

CREATE INDEX IF NOT EXISTS idx_analysis_grade_daily_run_horizon_date
  ON analysis_grade_daily (run_id, horizon, delivery_date DESC);
