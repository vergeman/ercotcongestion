-- Surface zonal outage MW in snapshot_meta
--
-- ERCOT outages_zonal reports per-load-zone MW out, split into:
--   - thermal/conventional (excludes IRR + new equipment)
--   - intermittent renewable (wind + solar + battery)
--
-- We don't have line- or generator-level outage detail. The column is JSONB
-- shaped like:
--   {
--     "south":   {"thermal_mw": 9481.0, "irr_mw": 1199.0},
--     "north":   {"thermal_mw": 11497.0, "irr_mw": 996.0},
--     "west":    {"thermal_mw": 1446.0,  "irr_mw": 3057.0},
--     "houston": {"thermal_mw": 7489.0,  "irr_mw": 0.0}
--   }

ALTER TABLE snapshot_meta
  ADD COLUMN IF NOT EXISTS outages_by_zone jsonb;
