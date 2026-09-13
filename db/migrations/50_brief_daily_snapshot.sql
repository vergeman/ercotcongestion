CREATE TABLE IF NOT EXISTS brief_daily_snapshot (
  run_id         TEXT NOT NULL,
  delivery_date  DATE NOT NULL,
  horizon        SMALLINT NOT NULL CHECK (horizon = 1),
  schema_version SMALLINT NOT NULL,
  hero           JSONB NOT NULL,
  details        JSONB NOT NULL,
  standouts      JSONB NOT NULL,
  computed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, delivery_date, horizon)
);
