"""
Verify bus -> weather zone mapping aligns with load_by_zone SQL keys.

Read-only diagnostic for plan/0003-bus-zone-remapping.md. Confirms the
preconditions for per-zone load scaling:

  1. String alignment: normalized ercot_weather_zone values in
     bus_ercot_weather_load_zones.csv match load_by_zone column keys
     character-for-character.
  2. Coverage: what fraction of buses in the CSV resolve to one of the
     8 weather zones vs. unmapped / null.

Usage:
    docker compose run --rm compute python /compute/verify_zone_mapping.py
    docker compose run --rm compute python /compute/verify_zone_mapping.py \\
        --ts 2025-07-30T21:00:00+00:00
"""
import sys
sys.path.insert(0, '/compute')

import argparse
from datetime import datetime, timezone

import pandas as pd
import psycopg
from psycopg.rows import dict_row

from config import PG_DSN, BUS_WEATHER_LOAD_ZONES_CSV


#DEFAULT_TS = "2025-07-30T21:00:00+00:00"
DEFAULT_TS = "2026-03-25T22:00:00+00:00"
NON_ZONE_KEYS = {'operating_day', 'hour_ending', 'total'}


def query_load_row(ts: datetime) -> dict:
    sql = """
        SELECT operating_day, hour_ending,
               coast, east, far_west, north, north_central,
               south_central, southern, west, total
        FROM load_by_zone
        WHERE interval_ts = %s
        ORDER BY dst_flag ASC
        LIMIT 1
    """
    with psycopg.connect(PG_DSN) as conn:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, (ts,))
            row = cur.fetchone()
    if row is None:
        raise LookupError(f"No load_by_zone row for interval_ts = {ts}")
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ts', default=DEFAULT_TS,
                    help="ISO timestamp to sample from load_by_zone")
    args = ap.parse_args()
    ts = datetime.fromisoformat(args.ts).astimezone(timezone.utc)

    # Load CSV and apply the same normalization as
    # operating_data_adapter._precompute (line 202).
    bz = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    bz['ercot_weather_zone_norm'] = (
        bz['ercot_weather_zone'].astype(str).str.lower().str.replace(' ', '_')
    )

    load_row = query_load_row(ts)
    load_zones = set(load_row.keys()) - NON_ZONE_KEYS
    bus_zones = set(bz['ercot_weather_zone_norm'].dropna().unique()) - {'nan'}

    # 1. String alignment
    print("=" * 60)
    print(f"String alignment check (sample ts = {ts.isoformat()})")
    print("=" * 60)
    print(f"  load_by_zone keys ({len(load_zones)}): {sorted(load_zones)}")
    print(f"  bus CSV zones     ({len(bus_zones)}): {sorted(bus_zones)}")

    bus_only = bus_zones - load_zones
    load_only = load_zones - bus_zones
    if not bus_only and not load_only:
        print("  Result: PASS — sets are identical.")
    else:
        print("  Result: FAIL")
        if bus_only:
            print(f"    In CSV but not load_by_zone: {sorted(bus_only)}")
        if load_only:
            print(f"    In load_by_zone but not CSV: {sorted(load_only)}")

    # 2. Coverage
    print()
    print("=" * 60)
    print("Coverage check (bus CSV)")
    print("=" * 60)
    total = len(bz)
    mapped = bz['ercot_weather_zone_norm'].isin(load_zones).sum()
    unmapped = total - mapped
    null_or_nan = bz['ercot_weather_zone'].isna().sum() + \
        (bz['ercot_weather_zone_norm'] == 'nan').sum()
    print(f"  Total buses:                  {total}")
    print(f"  Mapped to a real weather zone: {mapped} ({mapped / total:.1%})")
    print(f"  Unmapped / unrecognized:       {unmapped} ({unmapped / total:.1%})")
    print(f"    of which null/NaN:           {null_or_nan}")

    # Per-zone bus counts (useful for sanity-checking the share)
    print()
    print("  Buses per zone (normalized):")
    counts = (
        bz['ercot_weather_zone_norm']
        .value_counts(dropna=False)
        .sort_index()
    )
    for zone, n in counts.items():
        marker = "" if zone in load_zones else "  <-- not in load_by_zone"
        print(f"    {zone:<20} {n:>6}{marker}")


if __name__ == '__main__':
    main()
