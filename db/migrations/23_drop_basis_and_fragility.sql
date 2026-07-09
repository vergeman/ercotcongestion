-- 23_drop_basis_and_fragility.sql
--
-- Drop the retired `basis` and `fragility` columns/table. `fragility` was
-- already retired (write_snapshots.py wrote NULL into it); `basis` had one
-- live UI consumer (DetailCard) that's been removed. See plan 0076.

DROP INDEX IF EXISTS bus_snapshots_basis_idx;
DROP INDEX IF EXISTS bus_snapshots_fragility_idx;

ALTER TABLE bus_snapshots DROP COLUMN IF EXISTS basis;
ALTER TABLE bus_snapshots DROP COLUMN IF EXISTS fragility;

ALTER TABLE snapshot_meta DROP COLUMN IF EXISTS fragility_total;
ALTER TABLE snapshot_meta DROP COLUMN IF EXISTS fragility_top10_share;

DROP TABLE IF EXISTS bus_load_zones;
