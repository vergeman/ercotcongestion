-- 24_drop_rt_lmp.sql
--
-- Drop the retired `ercot_rt_lmp` table (NP6-788-CD, RT LMPs at Settlement
-- Points). It has zero downstream consumers in compute/, web/, or api/.
-- See plan 0077.

DROP TABLE IF EXISTS ercot_rt_lmp;
