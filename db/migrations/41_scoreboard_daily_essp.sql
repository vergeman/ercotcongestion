-- 41_scoreboard_daily_essp.sql
--
-- NP4-158-SG provides an independent labelled check of the SF map. These
-- values assess the served map and therefore live only on scoreboard_daily's
-- model row; baseline forecast rows remain NULL.

ALTER TABLE scoreboard_daily
  ADD COLUMN IF NOT EXISTS essp_precision REAL,
  ADD COLUMN IF NOT EXISTS essp_recall REAL;
