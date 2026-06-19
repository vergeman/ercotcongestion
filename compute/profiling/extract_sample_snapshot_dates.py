"""
Generate a fixed, reusable baseline of ~20 ERCOT snapshots spanning key regimes.
Used for rapid profiling and regression testing of PyPSA network modifications.

Usage:
    docker compose run --rm compute python /compute/profiling/sample_snapshots.py
"""

import json
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
from config import PG_DSN

OUTPUT_FILE = Path(__file__).parent / "reference_snapshots.json"

QUERIES = {
    "summer_peak": """
        WITH Ranked AS (
            SELECT interval_ts, n_binding_lines, total_load_mw,
                   ROW_NUMBER() OVER(PARTITION BY interval_ts::date ORDER BY n_binding_lines DESC, total_load_mw DESC) as rn
            FROM snapshot_meta
            WHERE status='ok' AND interval_ts >= '2025-01-01 UTC'
              AND EXTRACT(MONTH FROM interval_ts) IN (6,7,8,9)
        )
        SELECT interval_ts
        FROM Ranked
        WHERE rn = 1
        ORDER BY n_binding_lines DESC, total_load_mw DESC
        LIMIT 5;
    """,
    "high_wind_west": """
        WITH Ranked AS (
            SELECT interval_ts,
                   (wind_factor_by_region->>'west')::double precision as west_wind,
                   n_binding_lines,
                   ROW_NUMBER() OVER(PARTITION BY interval_ts::date ORDER BY (wind_factor_by_region->>'west')::double precision DESC, n_binding_lines DESC) as rn
            FROM snapshot_meta
            WHERE status='ok' AND interval_ts >= '2025-01-01 UTC'
              AND (wind_factor_by_region->>'west')::double precision > 0.40
        )
        SELECT interval_ts
        FROM Ranked
        WHERE rn = 1
        ORDER BY west_wind DESC, n_binding_lines DESC
        LIMIT 5;
    """,
    "mild_shoulder": """
        WITH Ranked AS (
            SELECT interval_ts, n_binding_lines, fragility_total, total_load_mw,
                   ROW_NUMBER() OVER(PARTITION BY interval_ts::date ORDER BY n_binding_lines ASC, fragility_total ASC, total_load_mw ASC) as rn
            FROM snapshot_meta
            WHERE status='ok' AND interval_ts >= '2025-01-01 UTC'
              AND EXTRACT(MONTH FROM interval_ts) IN (3,4,5,10,11)
        )
        SELECT interval_ts
        FROM Ranked
        WHERE rn = 1
        ORDER BY n_binding_lines ASC, fragility_total ASC, total_load_mw ASC
        LIMIT 5;
    """,
    "winter_peak": """
        WITH Ranked AS (
            SELECT interval_ts, total_load_mw, n_binding_lines,
                   ROW_NUMBER() OVER(PARTITION BY interval_ts::date ORDER BY total_load_mw DESC, n_binding_lines DESC) as rn
            FROM snapshot_meta
            WHERE status='ok' AND interval_ts >= '2025-01-01 UTC'
              AND EXTRACT(MONTH FROM interval_ts) IN (12,1,2)
        )
        SELECT interval_ts
        FROM Ranked
        WHERE rn = 1
        ORDER BY total_load_mw DESC, n_binding_lines DESC
        LIMIT 5;
    """
}
def generate_baseline():
    baseline = {}
    total_snapshots = 0

    with psycopg.connect(PG_DSN, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            for regime, sql in QUERIES.items():
                cur.execute(sql)
                # Convert datetime to ISO string for JSON serialization
                timestamps = [row['interval_ts'].isoformat() for row in cur.fetchall()]
                baseline[regime] = timestamps
                total_snapshots += len(timestamps)
                print(f"Captured {len(timestamps)} snapshots for '{regime}'")

    with open(OUTPUT_FILE, 'w') as f:
        json.dump(baseline, f, indent=2)

    print(f"\nSuccessfully wrote {total_snapshots} total snapshots to {OUTPUT_FILE.name}")

if __name__ == "__main__":
    generate_baseline()
