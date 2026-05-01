-- 09_basis_column.sql
--
-- Add basis to bus_snapshots abd a bus -> load_zone lookup table used by the
-- basis backfill
--

ALTER TABLE bus_snapshots
    ADD COLUMN IF NOT EXISTS basis double precision;

CREATE INDEX IF NOT EXISTS bus_snapshots_basis_idx
    ON bus_snapshots (basis)
    WHERE basis IS NOT NULL;

-- Static bus -> ERCOT load zone mapping. Mirrors bus_weather_load_zones.csv,
-- which is the source of truth (preprocess/assign_bus_weather_load_zones.py)
-- for bus - load_zone.
--
-- Loaded once by compute/backfill_basis.py from CSV; safe reinsert on CSV
-- change.
CREATE TABLE IF NOT EXISTS bus_load_zones (
    bus_id     text PRIMARY KEY,
    load_zone  text NOT NULL    -- 'north' | 'houston' | 'south' | 'west' | 'non_ercot'
);
