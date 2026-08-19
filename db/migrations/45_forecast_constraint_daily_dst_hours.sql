-- 45_forecast_constraint_daily_dst_hours.sql
--
-- 0133 re-cut the daily forecast block on the CT delivery day, so a block is
-- 23/24/25 hours long (DST transitions), not always 24.  The nonzero-hour
-- count rolled up from E_mu inherits that range: the fall-back day (e.g.
-- 2025-11-02) legitimately reaches 25 and tripped the old 0..24 check.

ALTER TABLE forecast_constraint_daily
  DROP CONSTRAINT IF EXISTS forecast_constraint_daily_binding_hours_chk;

ALTER TABLE forecast_constraint_daily
  ADD CONSTRAINT forecast_constraint_daily_binding_hours_chk
  CHECK (binding_hours BETWEEN 0 AND 25);
