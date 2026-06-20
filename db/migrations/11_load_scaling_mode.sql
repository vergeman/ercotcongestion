-- Record which load-scaling mode produced each snapshot.
--
-- 'zonal'           : per-weather-zone scale factors applied.
-- 'global_fallback' : one global scale factor applied. Used when:
--                       (a) any weather zone is missing data in load_by_zone,
--                       (b) the OPF was infeasible under zonal scaling and
--                           was retried with global scaling.
--
-- Rows produced before this column existed remain NULL. They predate
-- per-zone scaling and were always effectively global; left NULL rather
-- than back-labeled so analysis can distinguish pre-feature rows from
-- intentional fallback.

ALTER TABLE snapshot_meta
  ADD COLUMN IF NOT EXISTS load_scaling_mode text;
