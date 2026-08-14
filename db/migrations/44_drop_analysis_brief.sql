-- The v6 Brief is query-backed.  Its precomputed JSONB predecessor has no
-- remaining writer or reader, so remove it from deployed databases.
DROP TABLE IF EXISTS analysis_brief;
