-- =============================================================================
-- JOB 1: backfill_ingest
-- A day is "complete" only if ALL 5 endpoints have data for it.
-- =============================================================================
WITH days AS (
    SELECT generate_series(
        (SELECT LEAST(
            (SELECT MIN(interval_ts)::date    FROM ercot_zonal_lmp),
            (SELECT MIN(operating_date)       FROM outages_zonal),
            (SELECT MIN(operating_day)        FROM load_by_zone),
            (SELECT MIN(interval_ts)::date    FROM wind_hourly_regional),
            (SELECT MIN(interval_ts)::date    FROM solar_hourly_regional)
        )),
        (CURRENT_DATE - INTERVAL '1 day')::date,
        INTERVAL '1 day'
    )::date AS day
)
SELECT
    d.day,
    EXISTS (SELECT 1 FROM ercot_zonal_lmp        WHERE interval_ts::date    = d.day) AS zonal_lmp,
    EXISTS (SELECT 1 FROM outages_zonal          WHERE operating_date       = d.day) AS outages,
    EXISTS (SELECT 1 FROM load_by_zone           WHERE operating_day        = d.day) AS loads,
    EXISTS (SELECT 1 FROM wind_hourly_regional   WHERE interval_ts::date    = d.day) AS wind,
    EXISTS (SELECT 1 FROM solar_hourly_regional  WHERE interval_ts::date    = d.day) AS solar,
    (   EXISTS (SELECT 1 FROM ercot_zonal_lmp        WHERE interval_ts::date    = d.day)
    AND EXISTS (SELECT 1 FROM outages_zonal          WHERE operating_date       = d.day)
    AND EXISTS (SELECT 1 FROM load_by_zone           WHERE operating_day        = d.day)
    AND EXISTS (SELECT 1 FROM wind_hourly_regional   WHERE interval_ts::date    = d.day)
    AND EXISTS (SELECT 1 FROM solar_hourly_regional  WHERE interval_ts::date    = d.day)
    ) AS has_data,
    (CURRENT_DATE - d.day) AS days_ago
FROM days d
ORDER BY d.day;
 
