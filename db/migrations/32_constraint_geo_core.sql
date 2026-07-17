-- 32_constraint_geo_core.sql
--
-- Overview primitives for the revizualized SF map (plan/0092-0002). The flat
-- /map/constraints layer places each constraint at its |SF|-weighted MEAN
-- centroid (constraint_geo.lat/lon), which averages a bimodal constraint into
-- the empty middle between its lobes — so 1000+ constraints pile at the center
-- of the state. The overview instead positions each at its intensity CORE and
-- draws a mark chosen by TYPE:
--
--   core_lat/core_lon -- |SF|^2-weighted geometric median (Weiszfeld). Sits ON
--                     --   the strongest lobe, not between lobes, so markers
--                     --   de-pile off-center (compute.mu.geo::constraint_core).
--   ctype             -- 'gtc' | 'transmission' | 'radial', from the contingency
--                     --   string + rail signature (compute.mu.geo::constraint_type):
--                     --   gtc = region, transmission = corridor, radial = point.
--
-- Nullable and backfilled after the fit, like sf_stability: NULL for older runs
-- that predate the overview, and honest NULL for a constraint whose |SF| mass
-- lands entirely on uncoordinated settlement points (holes stay holes). ctype is
-- derivable from existing columns, so no CHECK constraint — the writer owns the
-- enum, the reader treats an unknown value as untyped.

ALTER TABLE constraint_geo ADD COLUMN IF NOT EXISTS core_lat REAL;
ALTER TABLE constraint_geo ADD COLUMN IF NOT EXISTS core_lon REAL;
ALTER TABLE constraint_geo ADD COLUMN IF NOT EXISTS ctype    TEXT;
