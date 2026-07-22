-- 34_constraint_geo_drop_coords.sql
--
-- Drop the constraint centroid + medoid coordinates from constraint_geo
-- (plan/0112). Nothing served them: the flat |SF|-mean centroid (lat/lon) was
-- unused on every /map/* endpoint, and the |SF|^2 geometric-median core
-- (core_lat/core_lon) was only the overview's radial-ring anchor + an invisible
-- hit target — both replaced by the peak-|SF| node + interactive marks. The
-- offline calc (compute.mu.geo.constraint_core / _weiszfeld) is deleted with them.
--
-- The zone/kV/spread metadata columns (zone_shares, kv_mean, kv_max, spread_km)
-- stay: they are unique to this table and cheap to keep, even though the plain
-- /map/constraints endpoint that served them was removed.
--
-- Deploy ordering: ship + deploy the api change (which stops selecting these
-- columns) BEFORE running this migration, or the running api 500s on the missing
-- columns until it is redeployed.

ALTER TABLE constraint_geo DROP COLUMN IF EXISTS lat;
ALTER TABLE constraint_geo DROP COLUMN IF EXISTS lon;
ALTER TABLE constraint_geo DROP COLUMN IF EXISTS core_lat;
ALTER TABLE constraint_geo DROP COLUMN IF EXISTS core_lon;
