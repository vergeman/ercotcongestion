-- =============================================================================
-- JOB 2: backfill_snapshots
-- A day has data if there's at least one snapshot_meta row with status='ok'.
-- (Use has_full_day to spot partial days: 24 hourly rows expected.)
-- =============================================================================
WITH days AS (
  SELECT generate_series(
    (SELECT MIN(interval_ts)::date FROM snapshot_meta),
    (CURRENT_DATE - INTERVAL '1 day')::date,
    INTERVAL '1 day'
  )::date AS day
)
SELECT
  d.day,
  COALESCE(s.ok_hours, 0) AS ok_hours,
  (COALESCE(s.ok_hours, 0) > 0)  AS has_data,
  (COALESCE(s.ok_hours, 0) = 24) AS has_full_day,
  (CURRENT_DATE - d.day) AS days_ago
  FROM days d
       LEFT JOIN (
         SELECT interval_ts::date AS day,
                COUNT(*) FILTER (WHERE status = 'ok') AS ok_hours
           FROM snapshot_meta
          GROUP BY interval_ts::date
       ) s ON s.day = d.day
 WHERE COALESCE(s.ok_hours, 0) <> 24
 ORDER BY d.day;

-- WITH days AS (
--   SELECT generate_series(
--     (SELECT MIN(interval_ts)::date FROM snapshot_meta),
--     (CURRENT_DATE - INTERVAL '1 day')::date,
--     INTERVAL '1 day'
--   )::date AS day
-- )
-- SELECT
--   d.day,
--   COALESCE(s.ok_hours, 0) AS ok_hours,
--   (COALESCE(s.ok_hours, 0) > 0)  AS has_data,
--   (COALESCE(s.ok_hours, 0) = 24) AS has_full_day,
--   (CURRENT_DATE - d.day) AS days_ago
--   FROM days d
--        LEFT JOIN (
--          SELECT interval_ts::date AS day,
--                 COUNT(*) FILTER (WHERE status = 'ok') AS ok_hours
--            FROM snapshot_meta
--           GROUP BY interval_ts::date
--        ) s ON s.day = d.day
--  ORDER BY d.day;
