-- 35_scoreboard_daily.sql
--
-- The LIVE scoreboard (plan/0102 Phase 3, 0003-live-grading). Where the backtest
-- board (34_scoreboard_weekly.sql) grades a pre-registered walk, this grades the
-- *served* forecast one day behind: grade_forecast_day(D) pulls the point forecast that
-- forecast_nodal actually served for delivery day D, scores it against realized
-- DAM SPP congestion (SPP - system_λ) with the SAME score_matrix the backtest
-- uses (compute/mu/score.py), and writes one row per source. Live and backtest
-- numbers are therefore the same currency (0003 spec §2.2 / §7).
--
-- run_id ties each grade to the MODEL VERSION that served it — the identical
-- run_id semantics as forecast_nodal / scoreboard_weekly — so a config change
-- starts a fresh, non-spliced live track rather than splicing two operating
-- points into one series. The write is idempotent by (run_id, delivery_date):
-- a re-grade of D under the same run_id replaces D's rows.
--
-- source is free text (oracle | model | persistence | climatology | null), no
-- CHECK — a new baseline the shared harness starts emitting rides through
-- without a migration, exactly as the weekly board. The `null` (flat) source is
-- the integrity comparator: score_matrix declines flat rows, so a live metric
-- that scores `null` above chance means the metric path regressed (spec §6).
--
-- Two metric families, same as the weekly board: screening + magnitude from
-- score_matrix (pooled_r2, mae, rank_spearman, sign_agree, topdecile_hit), and
-- the P50 band metrics (coverage80, band_width, pinball) — here measured live
-- from the served p10/p50/p90 against realized, on the model source only.
-- sf_coverage / model_coverage are the |μ|-mass coverage denominators the day's
-- skill must be read against (a collapse week is often a coverage gap, not lost
-- skill); every metric column is nullable so a NaN cell lands as NULL rather than
-- dropping the row (a declined/flat cell must read as absent, never as a score).

CREATE TABLE IF NOT EXISTS scoreboard_daily (
  run_id         TEXT NOT NULL,
  delivery_date  DATE NOT NULL,
  source         TEXT NOT NULL,   -- oracle | model | persistence | climatology | null

  -- Screening + magnitude currencies (score_matrix), identical to the weekly board.
  pooled_r2      REAL,
  mae            REAL,
  rank_spearman  REAL,
  sign_agree     REAL,
  topdecile_hit  REAL,

  -- Live P50 band metrics from the served p10/p50/p90 vs realized — model only.
  coverage80     REAL,
  band_width     REAL,
  pinball        REAL,

  -- Coverage denominators / grain the day's metrics were pooled over.
  sf_coverage    REAL,
  model_coverage REAL,
  n_hours        INT,
  n_nodes        INT,

  PRIMARY KEY (run_id, delivery_date, source)
);

-- The per-day serving read and the delete-then-write re-grade both slice by
-- (run_id, delivery_date).
CREATE INDEX IF NOT EXISTS idx_scoreboard_daily_run_date
  ON scoreboard_daily (run_id, delivery_date);

-- NOTE: miss-attribution (the scoreboard_miss decomposition + the prediction-time
-- forecast_snapshot it reads) is DEFERRED out of 0003 — the live grade above is
-- the shipped deliverable. When it returns it lands as its own migration; nothing
-- here depends on it.
