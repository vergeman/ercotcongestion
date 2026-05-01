"""
Backfill basis values for existing bus_snapshots rows.

basis = bus_lmp (model, already stored)  -  ERCOT zonal_lmp (hourly mean)

This script does NOT re-run OPF. The bus LMPs already in bus_snapshots are
joined in SQL against ercot_zonal_lmp_hourly via bus_load_zones. Net effect:
30-60 days of historical basis populated in seconds, not hours.

Usage:
    docker compose run --rm compute python /compute/backfill_basis.py
    docker compose run --rm compute python /compute/backfill_basis.py \
        --start 2026-02-19 --end 2026-04-23
    docker compose run --rm compute python /compute/backfill_basis.py --reload-zones-only

    Takes about ~2 minutes initially, be patient

Steps:
  1. Refresh bus_load_zones from bus_weather_load_zones.csv (idempotent).
  2. UPDATE bus_snapshots.basis where the corresponding zonal LMP is available.

Buses with load_zone='non_ercot' or zones with no zonal LMP at the timestamp
get basis = NULL (the row is not updated, leaving its existing value — usually
NULL — in place).
"""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone

import pandas as pd
import psycopg

from config import BUS_WEATHER_LOAD_ZONES_CSV, PG_DSN


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
)
log = logging.getLogger('backfill_basis')


# ---------------------------------------------------------------------------
# bus_load_zones refresh
# ---------------------------------------------------------------------------

def refresh_bus_load_zones(conn) -> int:
    """Load bus_weather_load_zones.csv into the bus_load_zones table.

    TRUNCATE + bulk INSERT. Static mapping; safe to fully replace.
    Returns the number of buses inserted.
    """
    log.info(f"Loading bus -> load_zone from {BUS_WEATHER_LOAD_ZONES_CSV}")
    df = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)

    if 'name' not in df.columns or 'ercot_load_zone' not in df.columns:
        raise ValueError(
            f"{BUS_WEATHER_LOAD_ZONES_CSV} must have 'name' and 'ercot_load_zone' "
            f"columns; got {df.columns.tolist()}"
        )

    df = df[['name', 'ercot_load_zone']].copy()
    df['name'] = df['name'].astype(str)
    df['ercot_load_zone'] = (
        df['ercot_load_zone']
        .where(df['ercot_load_zone'].notna(), 'non_ercot')
        .astype(str).str.lower().str.replace(' ', '_')
    )

    rows = list(df.itertuples(index=False, name=None))

    with conn.cursor() as cur:
        cur.execute("TRUNCATE bus_load_zones")
        cur.executemany(
            "INSERT INTO bus_load_zones (bus_id, load_zone) VALUES (%s, %s)",
            rows,
        )
    conn.commit()
    log.info(f"  Inserted {len(rows)} buses into bus_load_zones")

    # Quick distribution sanity check
    with conn.cursor() as cur:
        cur.execute(
            "SELECT load_zone, COUNT(*) FROM bus_load_zones GROUP BY load_zone ORDER BY 1"
        )
        for zone, n in cur.fetchall():
            log.info(f"    {zone:12s}: {n}")
    return len(rows)


# ---------------------------------------------------------------------------
# basis update
# ---------------------------------------------------------------------------
#
# basis = bs.lmp - z.lmp
#
# joined on bus_id,               tbl
# filter on interval
# ---                              ---
# bus_snapshots:                   bs
# bus_load_zones:                  blz
# ercot_zonal_lmp_hourly:          z
#
# NB: interval_ts is in UTC; no dst_flag handling needed, flag is for ingestion
# from ERCOT, which gets converted to UTC.

UPDATE_BASIS_SQL = """
UPDATE bus_snapshots bs
SET basis = bs.lmp - z.lmp
FROM bus_load_zones blz,
     ercot_zonal_lmp_hourly z
WHERE bs.bus_id = blz.bus_id
  AND z.load_zone = blz.load_zone
  AND z.interval_ts = bs.interval_ts
  AND bs.lmp IS NOT NULL
  AND blz.load_zone <> 'non_ercot'
  AND bs.interval_ts >= %s
  AND bs.interval_ts <  %s
"""


def backfill_basis(
    conn,
    start: datetime | None,
    end: datetime | None,
) -> int:
    """Recompute basis for all bus_snapshots rows in [start, end).

    If start/end are None, derive them from the snapshot_meta range.
    Returns rows updated.
    """
    if start is None or end is None:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT MIN(interval_ts), MAX(interval_ts) FROM snapshot_meta WHERE status = 'ok'"
            )
            row = cur.fetchone()
        if row is None or row[0] is None:
            log.warning("No snapshot_meta rows; nothing to backfill.")
            return 0
        start = start or row[0]
        # end is exclusive; bump max by 1 second to include it.
        end = end or row[1].replace(microsecond=0)

    log.info(f"Backfilling basis for [{start}, {end})...")
    t0 = time.time()
    with conn.cursor() as cur:
        cur.execute(UPDATE_BASIS_SQL, (start, end))
        n = cur.rowcount
    conn.commit()
    log.info(f"  Updated {n} rows in {time.time() - t0:.1f}s")

    # Coverage diagnostic
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*)                               AS total_rows,
                COUNT(*) FILTER (WHERE basis IS NOT NULL) AS basis_rows,
                COUNT(DISTINCT interval_ts)            AS total_ts,
                COUNT(DISTINCT interval_ts) FILTER (WHERE basis IS NOT NULL) AS basis_ts
            FROM bus_snapshots
            WHERE interval_ts >= %s AND interval_ts < %s
              AND lmp IS NOT NULL
            """,
            (start, end),
        )
        total, with_basis, total_ts, basis_ts = cur.fetchone()
    pct = 100.0 * with_basis / total if total else 0.0
    log.info(
        f"  Coverage: {with_basis}/{total} rows have basis ({pct:.1f}%); "
        f"{basis_ts}/{total_ts} timestamps have any basis"
    )
    return n


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_ts(s: str) -> datetime:
    if 'T' not in s and ' ' not in s:
        s = s + 'T00:00'
    elif s.count(':') == 0:
        s = s + ':00'
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', help='UTC start (inclusive). Default: min snapshot_meta.')
    ap.add_argument('--end',   help='UTC end (exclusive). Default: max snapshot_meta + 1s.')
    ap.add_argument('--reload-zones-only', action='store_true',
                    help='Refresh bus_load_zones from CSV and exit.')
    ap.add_argument('--skip-zone-reload', action='store_true',
                    help='Skip the bus_load_zones refresh (use existing table).')
    args = ap.parse_args()

    conn = psycopg.connect(PG_DSN)

    if not args.skip_zone_reload:
        refresh_bus_load_zones(conn)

    if args.reload_zones_only:
        return

    start = parse_ts(args.start) if args.start else None
    end   = parse_ts(args.end)   if args.end   else None
    backfill_basis(conn, start, end)


if __name__ == '__main__':
    main()
