-- =============================================================================
-- JOB 3: backfill_basis
-- A day has data if any bus_snapshots row that day has a non-null basis.
-- (pct_basis tells you coverage within the day; <100 = partial.)
-- =============================================================================
WITH days AS (
    SELECT generate_series(
        (SELECT MIN(interval_ts)::date FROM bus_snapshots WHERE lmp IS NOT NULL),
        (CURRENT_DATE - INTERVAL '1 day')::date,
        INTERVAL '1 day'
    )::date AS day
)
SELECT
    d.day,
    COALESCE(b.rows_with_lmp,   0) AS rows_with_lmp,
    COALESCE(b.rows_with_basis, 0) AS rows_with_basis,
    (COALESCE(b.rows_with_basis, 0) > 0) AS has_data,
    ROUND(100.0 * COALESCE(b.rows_with_basis, 0)
                / NULLIF(b.rows_with_lmp, 0), 1) AS pct_basis,
    (CURRENT_DATE - d.day) AS days_ago
FROM days d
LEFT JOIN (
    SELECT interval_ts::date AS day,
           COUNT(*) FILTER (WHERE lmp   IS NOT NULL) AS rows_with_lmp,
           COUNT(*) FILTER (WHERE basis IS NOT NULL) AS rows_with_basis
    FROM bus_snapshots
    GROUP BY interval_ts::date
) b ON b.day = d.day
ORDER BY d.day;
