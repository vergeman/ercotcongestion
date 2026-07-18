-- 33_drop_binding_proximity.sql
--
-- Drop the legacy binding-proximity tables (plan/0093-0004). Created in
-- 22_implied_binding_proximity.sql to serve the bp_ercot panel + its promote
-- pointer; superseded by the SF tables (25_implied_shift_factors.sql) the v3
-- map serves. After 0093-0001..0003 no code references either table: the API
-- no longer reads the pointer (/meta), the runner is SF-only, and the bp
-- modules/persist helpers are gone.
--
-- Forward-only, IF EXISTS so it applies clean whether or not the tables are
-- present. Dropping the pointer table also drops its promoted_at history; that
-- clock is retired (MetaResponse.promoted_at is always null now).

DROP TABLE IF EXISTS implied_binding_proximity;
DROP TABLE IF EXISTS implied_binding_proximity_current;
