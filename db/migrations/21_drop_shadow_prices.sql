-- 21_drop_shadow_prices.sql
--
-- Retire NP6-86-CD (SCED/5-min shadow prices). The table has no downstream
-- reader; superseded by ercot_dam_shadow_prices (NP4-191-CD, DAM/hourly).

DROP TABLE IF EXISTS shadow_prices;
