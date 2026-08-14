-- Store the complete rendered half alongside the compact metric columns.  The
-- latter remain the efficient history series; this snapshot lets /analysis/grade
-- avoid re-running a full-artifact calculation for an already-settled day.

ALTER TABLE analysis_grade_daily
  ADD COLUMN IF NOT EXISTS detail JSONB;
