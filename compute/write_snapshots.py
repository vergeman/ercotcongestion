"""
Snapshot writer: iterate hourly timestamps, run OPF for each, persist results.

Loops over a UTC timestamp range. For each hour:
  1. Reload network from disk (avoids mutation accumulation across iterations)
  2. Build operating data via the adapter
  3. Apply to network and run compute_snapshot
  4. Insert per-bus results into bus_snapshots
  5. Insert per-snapshot meta into snapshot_meta

Failures (infeasibility, missing data, etc.) are logged in snapshot_meta
with status != 'ok' and don't block the loop.

Usage:
    docker compose run --rm compute python /compute/write_snapshots.py \
        --start 2026-02-19 --end 2026-04-23
    docker compose run --rm compute python /compute/write_snapshots.py \
        --start 2026-03-25T22 --end 2026-03-25T22  # single hour test
"""
from __future__ import annotations

import gc
import resource
import argparse
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import psycopg
import pypsa
from config import (
    NETWORK_NC, MARGINAL_COSTS_CSV, BUS_WEATHER_LOAD_ZONES_CSV, GENERATOR_MATCHES_ENRICHED_CSV, PG_DSN,
)
from operating_data_adapter import OperatingDataAdapter
from snapshot import run_snapshot_for_ts


# ---------------------------------------------------------------------------
# Logging — quiet PyPSA / linopy / HiGHS noise during bulk runs
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
)
log = logging.getLogger('snapshot_writer')

for noisy in ('pypsa', 'linopy', 'highspy', 'pypsa.consistency',
              'pypsa.optimization', 'pypsa.optimization.optimize',
              'pypsa.network.io', 'snapshot'):
    logging.getLogger(noisy).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Postgres I/O
# ---------------------------------------------------------------------------

UPSERT_BUS_SNAPSHOT_SQL = """
    INSERT INTO bus_snapshots (interval_ts, bus_id, fragility, lmp, basis)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT (interval_ts, bus_id) DO UPDATE SET
        fragility = EXCLUDED.fragility,
        lmp       = EXCLUDED.lmp,
        basis     = EXCLUDED.basis
"""

UPSERT_META_SQL = """
    INSERT INTO snapshot_meta (
        interval_ts, status, computed_at,
        objective_cost, total_load_mw, total_gen_mw, n_binding_lines,
        lmp_min, lmp_mean, lmp_max,
        fragility_total, fragility_top10_share,
        binding_lines, top_contingencies, dispatch_by_carrier,
        wind_factor_by_region, solar_factor_by_region,
        outage_posting_ts, outages_by_zone, error_message
    )
    VALUES (
        %s, %s, now(),
        %s, %s, %s, %s,
        %s, %s, %s,
        %s, %s,
        %s::jsonb, %s::jsonb, %s::jsonb,
        %s::jsonb, %s::jsonb,
        %s, %s::jsonb, %s
    )
    ON CONFLICT (interval_ts) DO UPDATE SET
        status                 = EXCLUDED.status,
        computed_at            = EXCLUDED.computed_at,
        objective_cost         = EXCLUDED.objective_cost,
        total_load_mw          = EXCLUDED.total_load_mw,
        total_gen_mw           = EXCLUDED.total_gen_mw,
        n_binding_lines        = EXCLUDED.n_binding_lines,
        lmp_min                = EXCLUDED.lmp_min,
        lmp_mean               = EXCLUDED.lmp_mean,
        lmp_max                = EXCLUDED.lmp_max,
        fragility_total        = EXCLUDED.fragility_total,
        fragility_top10_share  = EXCLUDED.fragility_top10_share,
        binding_lines          = EXCLUDED.binding_lines,
        top_contingencies      = EXCLUDED.top_contingencies,
        dispatch_by_carrier    = EXCLUDED.dispatch_by_carrier,
        wind_factor_by_region  = EXCLUDED.wind_factor_by_region,
        solar_factor_by_region = EXCLUDED.solar_factor_by_region,
        outage_posting_ts      = EXCLUDED.outage_posting_ts,
        outages_by_zone        = EXCLUDED.outages_by_zone,
        error_message          = EXCLUDED.error_message
"""


def _f(series, key):
    """Series lookup -> float or None (NaN-safe)."""
    if series is None or key not in series.index:
        return None
    v = series.get(key)
    if v is None or pd.isna(v):
        return None
    return float(v)

def write_snapshot(conn, ts: datetime, result: dict, op: dict, network) -> None:
    """Persist a successful snapshot to Postgres."""
    fragility = result['fragility']
    lmps      = result['lmps']
    basis     = result.get('basis')

    # bus_snapshots: one row per bus
    bus_rows = []
    for bus_id in network.buses.index:
        bus_rows.append((
            ts,
            str(bus_id),
            _f(fragility, bus_id),
            _f(lmps, bus_id),
            _f(basis, bus_id)
        ))

    # snapshot_meta: per-snapshot diagnostics
    meta = result['meta']
    shadow = result['shadow_prices']
    binding_lines_json = [
        {'line': str(line), 'shadow_price': float(shadow[line])}
        for line in shadow.index[:20]   # cap at 20 to keep JSONB compact
    ]
    contingencies = result['top_contingencies']
    contingencies_json = [
        {'line': str(idx), 'stress': float(row['stress'])}
        for idx, row in contingencies.head(10).iterrows()
    ]
    dispatch_by_carrier = (
        network.generators.assign(p=network.generators_t.p.iloc[0])
        .groupby('carrier')['p'].sum().round(0).to_dict()
    )
    op_meta = op.get('meta', {})

    meta_row = (
        ts,
        result['status'],
        meta.get('objective_cost'),
        meta.get('total_load_mw'),
        meta.get('total_gen_mw'),
        meta.get('n_binding_lines'),
        meta.get('lmp_min'),
        meta.get('lmp_mean'),
        meta.get('lmp_max'),
        meta.get('fragility_total'),
        meta.get('fragility_top10_share'),
        json.dumps(binding_lines_json),
        json.dumps(contingencies_json),
        json.dumps({k: float(v) for k, v in dispatch_by_carrier.items()}),
        json.dumps(op_meta.get('wind_factor_by_region', {})),
        json.dumps(op_meta.get('solar_factor_by_region', {})),
        op_meta.get('outage_posting_ts'),
        json.dumps(op_meta.get('outages_by_zone')),
        None,  # error_message
    )

    with conn.cursor() as cur:
        cur.executemany(UPSERT_BUS_SNAPSHOT_SQL, bus_rows)
        cur.execute(UPSERT_META_SQL, meta_row)
    conn.commit()


def write_failure(conn, ts: datetime, status: str, error_message: str) -> None:
    """Record a failed snapshot in snapshot_meta with status != 'ok'."""
    meta_row = (
        ts, status,
        None, None, None, None,
        None, None, None,
        None, None,
        None, None, None,
        None, None,
        None,           # outage_posting_ts
        None,           # outages_by_zone
        error_message,
    )
    with conn.cursor() as cur:
        cur.execute(UPSERT_META_SQL, meta_row)
    conn.commit()


# ---------------------------------------------------------------------------
# Per-snapshot pipeline
# ---------------------------------------------------------------------------

def compute_one(
    ts: datetime,
    adapter: OperatingDataAdapter,
    mc: pd.DataFrame,
) -> tuple[str, dict | None, dict | None, pypsa.Network | None]:
    """Build operating_data, run OPF, return (status, result, op, network).

    Returns (result['status'], result, op, n) on success.
    Returns ('<category>:<reason>', None, None, None) on failure.
    """

    try:
        result, op, n = run_snapshot_for_ts(ts, adapter, mc)
    except LookupError as e:
        return f'missing_data:{e}', None, None, None
    except FileNotFoundError as e:
        return f'config_error:{e}', None, None, None
    except Exception as e:
        return f'opf_error:{type(e).__name__}:{e}', None, None, None

    return result['status'], result, op, n


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def parse_ts(s: str) -> datetime:
    """Parse a flexible ISO-ish timestamp; assume UTC if naive."""
    # Allow shapes like '2026-03-25', '2026-03-25T22', '2026-03-25T22:00'
    if 'T' not in s and ' ' not in s:
        s = s + 'T00:00'
    elif s.count(':') == 0:
        s = s + ':00'
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def hourly_range(start: datetime, end: datetime):
    """Yield UTC timestamps at hourly intervals from start to end inclusive."""
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(hours=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', required=True, help='UTC start (e.g. 2026-02-19)')
    ap.add_argument('--end',   required=True, help='UTC end (e.g. 2026-04-23)')
    ap.add_argument('--skip-existing', action='store_true',
                    help='Skip timestamps already present in snapshot_meta with status=ok')
    args = ap.parse_args()

    start = parse_ts(args.start)
    end   = parse_ts(args.end)

    # Connect once for the lifetime of the loop
    conn = psycopg.connect(PG_DSN)

    # Load static reference data once
    log.info("Loading static reference data...")
    mc                   = pd.read_csv(MARGINAL_COSTS_CSV, index_col=0)
    bus_weather_zones    = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    gen_enriched         = pd.read_csv(GENERATOR_MATCHES_ENRICHED_CSV)

    # The adapter needs a network for static precomputation; load once for this purpose
    log.info("Initializing adapter...")
    n_init = pypsa.Network(NETWORK_NC)
    adapter = OperatingDataAdapter(conn, gen_enriched, bus_weather_zones, n_init)

    # Optionally skip already-computed timestamps
    existing = set()
    if args.skip_existing:
        with conn.cursor() as cur:
            cur.execute("SELECT interval_ts FROM snapshot_meta WHERE status = 'ok'")
            existing = {row[0] for row in cur.fetchall()}
        log.info(f"Skip-existing: {len(existing)} timestamps already done")

    timestamps = list(hourly_range(start, end))
    n_total = len(timestamps)
    log.info(f"Processing {n_total} timestamps from {start} to {end}")

    counts = {'ok': 0, 'infeasible': 0, 'missing_data': 0, 'other_error': 0, 'skipped': 0}
    t_start = time.time()

    for i, ts in enumerate(timestamps, 1):
        if ts in existing:
            counts['skipped'] += 1
            continue

        log.info(f"compute_one() start: {ts}")

        status, result, op, n = compute_one(ts, adapter, mc)

        try:
            if status == 'ok':
                write_snapshot(conn, ts, result, op, n)
                counts['ok'] += 1
            elif status == 'infeasible':
                write_failure(conn, ts, 'infeasible', None)
                counts['infeasible'] += 1
            elif status.startswith('missing_data'):
                write_failure(conn, ts, 'missing_data', status)
                counts['missing_data'] += 1
            else:
                write_failure(conn, ts, 'error', status)
                counts['other_error'] += 1
        except Exception as e:
            log.error(f"DB write failure at {ts}: {e}")
            conn.rollback()


        # Cleanup - there's a growing memory leak when running
        # so just explicitly clear to prevent OOM
        if n is not None:

            # Clear fat linopy model
            if hasattr(n, 'model'):
                del n.model

        del n, result, op

        gc.collect()


        # Progress every 24 iterations (one ERCOT day)
        if i % 24 == 0 or i == n_total:
            elapsed = time.time() - t_start
            rate = i / elapsed
            eta = (n_total - i) / rate if rate > 0 else 0
            rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024

            log.info(
                f"[{i}/{n_total}] {ts.isoformat()} {status:>12s}  "
                f"ok={counts['ok']} infeas={counts['infeasible']} "
                f"miss={counts['missing_data']} err={counts['other_error']}  "
                f"rate={rate:.2f}/s  ETA={eta/60:.1f}min  "
                f"RSS={rss_mb:.0f} MB"
            )




    log.info(
        f"Done. {counts['ok']} ok, {counts['infeasible']} infeasible, "
        f"{counts['missing_data']} missing, {counts['other_error']} errors, "
        f"{counts['skipped']} skipped."
    )


if __name__ == '__main__':
    main()
