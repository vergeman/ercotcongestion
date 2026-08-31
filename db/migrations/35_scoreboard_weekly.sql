-- 34_scoreboard_weekly.sql
--
-- The backtest scoreboard (plan/0102 Phase 3, spec-phase3-scoreboard.md §2.1).
-- The pre-registered currencies already exist per (week x source x regime) in
-- compute/mu/mu_score_weekly.csv, and the P50 band metrics per week (model source
-- only) in mu_bands_weekly.csv. This table is where the reshape-and-serve loader
-- (compute.jobs.backfill_scoreboard) lands them so the API serves indexed rows, not
-- files. It is NOT new measurement — the numbers are transcribed as-is (§0, §6).
--
-- run_id names the *model version* that produced the board (same run_id semantics
-- as forecast_nodal), so a config change starts a fresh, non-spliced track rather
-- than splicing two operating points into one series. The loader is idempotent by
-- delete-then-copy scoped to run_id.
--
-- source is free text (oracle | model | persistence | climatology | model_clim |
-- null) — no CHECK, so a new baseline the harness starts emitting rides through
-- without a migration. regime is `all` or a net-load quintile (net_load_0..N) /
-- named regime. coverage80/band_width/pinball come from the bands CSV and are only
-- populated on the (source='model', regime='all') rows they were measured on;
-- every metric column is nullable so a NaN cell lands as NULL rather than dropping
-- the row.

CREATE TABLE IF NOT EXISTS scoreboard_weekly (
  run_id         TEXT NOT NULL,
  week           DATE NOT NULL,
  source         TEXT NOT NULL,   -- oracle | model | persistence | climatology | model_clim | null
  regime         TEXT NOT NULL,   -- all | net_load_0..N | summer_peak | ...

  -- Screening + magnitude currencies (mu_score_weekly.csv).
  pooled_r2      REAL,
  mae            REAL,
  rank_spearman  REAL,
  sign_agree     REAL,
  topdecile_hit  REAL,

  -- P50 band metrics (mu_bands_weekly.csv) — model source, `all` regime only.
  coverage80     REAL,
  band_width     REAL,
  pinball        REAL,

  -- Denominators / coverage the metrics were pooled over.
  sf_coverage    REAL,
  model_coverage REAL,
  n_hours        INT,
  n_nodes        INT,

  PRIMARY KEY (run_id, week, source, regime)
);
