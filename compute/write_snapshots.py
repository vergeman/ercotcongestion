"""
Snapshot writer: iterate hourly timestamps in weekly chunks, batched-solve OPF,
persist per-snapshot results.

Loops over a UTC timestamp range partitioned into chunks (default 168 = 1 week
of hourly snapshots). For each chunk:
  1. Build adapter operating data for every ts in the chunk
  2. compute_snapshot_batch(n, ts_list, op_by_ts) builds the PyPSA model
     once and solves all snapshots in a single HiGHS call
  3. Persist per-ts results (bus_snapshots + snapshot_meta)
  4. On chunk-level infeasibility: retry each ts individually with
     force_global_load_sf=True

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
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import psycopg
import pypsa
from config import (
    NETWORK_NC, MARGINAL_COSTS_CSV, BUS_WEATHER_LOAD_ZONES_CSV, GENERATOR_MATCHES_ENRICHED_CSV, PG_DSN,
)
from operating_conditions import apply_static_mutations
from operating_data_adapter import OperatingDataAdapter
from snapshot import compute_snapshot_batch
from congestion.compute import compute_congestion
from congestion.metrics import (
    build_dispatch_per_bus, build_hub_lmps, build_load_per_bus,
)
from congestion.system_lambda_estimators import (
    lambda_kkt_clean_median, lambda_merit_order,
)

# Hub centroid table drives build_hub_lmps. Load once at module init so every
# snapshot reuses the same DataFrame (per plan 0053).
HUB_CENTROIDS_CSV = Path("/data/processed/hubs_lz_centroids.csv")
_HUB_CENTROIDS = pd.read_csv(HUB_CENTROIDS_CSV).set_index('settlement_point')


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
              'pypsa.network.io'):
    logging.getLogger(noisy).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Postgres I/O
# ---------------------------------------------------------------------------

UPSERT_BUS_SNAPSHOT_SQL = """
    INSERT INTO bus_snapshots (
        interval_ts, bus_id,
        modeled_congestion, binding_proximity,
        lmp, dispatch
    )
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (interval_ts, bus_id) DO UPDATE SET
        modeled_congestion = EXCLUDED.modeled_congestion,
        binding_proximity  = EXCLUDED.binding_proximity,
        lmp                = EXCLUDED.lmp,
        dispatch           = EXCLUDED.dispatch
"""

UPSERT_META_SQL = """
    INSERT INTO snapshot_meta (
        interval_ts, status, computed_at,
        objective_cost, total_load_mw, total_gen_mw, n_binding_lines,
        lmp_min, lmp_mean, lmp_max,
        modeled_congestion_total, modeled_congestion_abs_total,
        modeled_congestion_top10_share,
        binding_proximity_max, binding_proximity_p95,
        binding_lines, top_contingencies, dispatch_by_carrier,
        wind_factor_by_region, solar_factor_by_region,
        outage_posting_ts, outages_by_zone, error_message,
        load_scaling_mode,
        system_lambda_kkt, system_lambda_merit_order, load_shed_mw,
        hub_lmps, reference_prices
    )
    VALUES (
        %s, %s, now(),
        %s, %s, %s, %s,
        %s, %s, %s,
        %s, %s,
        %s,
        %s, %s,
        %s::jsonb, %s::jsonb, %s::jsonb,
        %s::jsonb, %s::jsonb,
        %s, %s::jsonb, %s,
        %s,
        %s, %s, %s,
        %s::jsonb, %s::jsonb
    )
    ON CONFLICT (interval_ts) DO UPDATE SET
        status                          = EXCLUDED.status,
        computed_at                     = EXCLUDED.computed_at,
        objective_cost                  = EXCLUDED.objective_cost,
        total_load_mw                   = EXCLUDED.total_load_mw,
        total_gen_mw                    = EXCLUDED.total_gen_mw,
        n_binding_lines                 = EXCLUDED.n_binding_lines,
        lmp_min                         = EXCLUDED.lmp_min,
        lmp_mean                        = EXCLUDED.lmp_mean,
        lmp_max                         = EXCLUDED.lmp_max,
        modeled_congestion_total        = EXCLUDED.modeled_congestion_total,
        modeled_congestion_abs_total    = EXCLUDED.modeled_congestion_abs_total,
        modeled_congestion_top10_share  = EXCLUDED.modeled_congestion_top10_share,
        binding_proximity_max           = EXCLUDED.binding_proximity_max,
        binding_proximity_p95           = EXCLUDED.binding_proximity_p95,
        binding_lines                   = EXCLUDED.binding_lines,
        top_contingencies               = EXCLUDED.top_contingencies,
        dispatch_by_carrier             = EXCLUDED.dispatch_by_carrier,
        wind_factor_by_region           = EXCLUDED.wind_factor_by_region,
        solar_factor_by_region          = EXCLUDED.solar_factor_by_region,
        outage_posting_ts               = EXCLUDED.outage_posting_ts,
        outages_by_zone                 = EXCLUDED.outages_by_zone,
        error_message                   = EXCLUDED.error_message,
        load_scaling_mode               = EXCLUDED.load_scaling_mode,
        system_lambda_kkt               = EXCLUDED.system_lambda_kkt,
        system_lambda_merit_order       = EXCLUDED.system_lambda_merit_order,
        load_shed_mw                    = EXCLUDED.load_shed_mw,
        hub_lmps                        = EXCLUDED.hub_lmps,
        reference_prices                = EXCLUDED.reference_prices
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
    mc        = result['modeled_congestion']
    bp        = result['binding_proximity']
    lmps      = result['lmps']

    # Per-bus dispatch: aggregate generator dispatch to bus totals. NaN
    # (→ NULL) at buses with no generators; _f handles that conversion. Also
    # feeds reference_prices below.
    dispatch_per_bus = None
    try:
        dispatch_per_bus = build_dispatch_per_bus(result['dispatch'], network)
    except Exception as e:
        log.warning(f"build_dispatch_per_bus failed at {ts}: {e}")

    bus_rows = []
    for bus_id in network.buses.index:
        bus_rows.append((
            ts,
            str(bus_id),
            _f(mc, bus_id),
            _f(bp, bus_id),
            _f(lmps, bus_id),
            _f(dispatch_per_bus, bus_id),
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
    naive_ts = pd.Timestamp(ts).tz_convert('UTC').tz_localize(None) \
        if pd.Timestamp(ts).tzinfo is not None else pd.Timestamp(ts)
    gp_ts = network.generators_t.p.loc[naive_ts]
    dispatch_by_carrier = (
        network.generators.assign(p=gp_ts)
        .groupby('carrier')['p'].sum().round(0).to_dict()
    )
    op_meta = op.get('meta', {})

    # KKT/merit-order λ estimates. Each in its own try/except so a failure in
    # one leaves the column NULL rather than aborting the write.
    system_lambda_kkt = None
    try:
        system_lambda_kkt = lambda_kkt_clean_median(network, naive_ts)
    except Exception as e:
        log.warning(f"system_lambda_kkt failed at {ts}: {e}")

    system_lambda_mo = None
    try:
        system_lambda_mo = lambda_merit_order(network, naive_ts)
    except Exception as e:
        log.warning(f"system_lambda_merit_order failed at {ts}: {e}")

    load_shed_mw = float(result['meta'].get('load_shed_total_mw', 0.0))

    hub_lmps: dict = {}
    try:
        hub_lmps = build_hub_lmps(lmps, network, _HUB_CENTROIDS)
    except Exception as e:
        log.warning(f"build_hub_lmps failed at {ts}: {e}")

    loads_per_bus = None
    try:
        loads_per_bus = build_load_per_bus(network, ts)
    except Exception as e:
        log.warning(f"build_load_per_bus failed at {ts}: {e}")

    reference_prices: dict = {}
    try:
        _cong, reference_prices = compute_congestion(
            lmps, hub_lmps,
            loads=loads_per_bus, dispatch=dispatch_per_bus,
            system_lambda_kkt=system_lambda_kkt,
            system_lambda_merit_order=system_lambda_mo,
        )
    except Exception as e:
        log.warning(f"reference_prices failed at {ts}: {e}")

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
        meta.get('modeled_congestion_total'),
        meta.get('modeled_congestion_abs_total'),
        meta.get('modeled_congestion_top10_share'),
        meta.get('binding_proximity_max'),
        meta.get('binding_proximity_p95'),
        json.dumps(binding_lines_json),
        json.dumps(contingencies_json),
        json.dumps({k: float(v) for k, v in dispatch_by_carrier.items()}),
        json.dumps(op_meta.get('wind_factor_by_region', {})),
        json.dumps(op_meta.get('solar_factor_by_region', {})),
        op_meta.get('outage_posting_ts'),
        json.dumps(op_meta.get('outages_by_zone')),
        None,  # error_message
        op_meta.get('load_scaling_mode'),
        system_lambda_kkt,
        system_lambda_mo,
        load_shed_mw,
        json.dumps(hub_lmps),
        json.dumps(reference_prices),
    )

    with conn.cursor() as cur:
        cur.executemany(UPSERT_BUS_SNAPSHOT_SQL, bus_rows)
        cur.execute(UPSERT_META_SQL, meta_row)
    conn.commit()


def write_failure(
    conn,
    ts: datetime,
    status: str,
    error_message: str | None,
    load_scaling_mode: str | None = None,
) -> None:
    """Record a failed snapshot in snapshot_meta with status != 'ok'."""
    meta_row = (
        ts, status,
        None, None, None, None,     # objective_cost, total_load, total_gen, n_binding
        None, None, None,           # lmp_min/mean/max
        None, None, None,           # modeled_congestion_total/abs_total/top10_share
        None, None,                 # binding_proximity_max/p95
        None, None, None,           # binding_lines, top_contingencies, dispatch_by_carrier
        None, None,                 # wind_factor_by_region, solar_factor_by_region
        None,                       # outage_posting_ts
        None,                       # outages_by_zone
        error_message,
        load_scaling_mode,
        None, None, None,           # system_lambda_kkt, system_lambda_merit_order, load_shed_mw
        None, None,                 # hub_lmps, reference_prices
    )
    with conn.cursor() as cur:
        cur.execute(UPSERT_META_SQL, meta_row)
    conn.commit()


# ---------------------------------------------------------------------------
# Per-chunk pipeline
# ---------------------------------------------------------------------------

def _build_op_by_ts(
    ts_list: list[datetime],
    adapter: OperatingDataAdapter,
    *,
    force_global_load_sf: bool = False,
) -> tuple[dict[datetime, dict], dict[datetime, str]]:
    """Run adapter.build for each ts. Returns (op_by_ts, errors_by_ts)."""
    op_by_ts: dict[datetime, dict] = {}
    errors: dict[datetime, str] = {}
    for ts in ts_list:
        try:
            op_by_ts[ts] = adapter.build(
                ts, force_global_load_sf=force_global_load_sf
            )
        except LookupError as e:
            errors[ts] = f'missing_data:{e}'
        except FileNotFoundError as e:
            errors[ts] = f'config_error:{e}'
        except Exception as e:
            errors[ts] = f'opf_error:{type(e).__name__}:{e}'
    return op_by_ts, errors


def compute_chunk(
    ts_list: list[datetime],
    adapter: OperatingDataAdapter,
    n: pypsa.Network,
) -> dict[datetime, tuple[str, dict | None, dict | None]]:
    """Solve a chunk via compute_snapshot_batch. Returns
    {ts: (status, result, op)} for every ts in ts_list.

    On chunk-level infeasibility, retries each ts individually with
    force_global_load_sf=True (mirrors the legacy zonal→global retry).
    """
    out: dict[datetime, tuple[str, dict | None, dict | None]] = {}

    op_by_ts, errors = _build_op_by_ts(ts_list, adapter)
    for ts, err in errors.items():
        out[ts] = (err, None, None)

    solvable = [ts for ts in ts_list if ts not in errors]
    if not solvable:
        return out

    try:
        results = compute_snapshot_batch(n, solvable, op_by_ts)
    except Exception as e:
        err = f'opf_error:{type(e).__name__}:{e}'
        for ts in solvable:
            out[ts] = (err, None, op_by_ts.get(ts))
        return out

    if all(r['status'] == 'infeasible' for r in results.values()):
        log.warning(
            f"chunk infeasible [{solvable[0]}..{solvable[-1]}], "
            "retrying ts-by-ts with global load scale factor"
        )
        for ts in solvable:
            retry_op, retry_err = _build_op_by_ts(
                [ts], adapter, force_global_load_sf=True
            )
            if ts in retry_err:
                out[ts] = (retry_err[ts], None, None)
                continue
            try:
                retry_results = compute_snapshot_batch(n, [ts], retry_op)
            except Exception as e:
                out[ts] = (
                    f'opf_error:retry:{type(e).__name__}:{e}',
                    None, retry_op.get(ts),
                )
                continue
            r = retry_results[ts]
            out[ts] = (r['status'], r, retry_op[ts])
        return out

    for ts, r in results.items():
        out[ts] = (r['status'], r, op_by_ts[ts])
    return out


def _clear_time_varying(n: pypsa.Network) -> None:
    """Drop linopy model + per-snapshot DataFrames to keep RSS flat across chunks."""
    if hasattr(n, 'model'):
        try:
            del n.model
        except AttributeError:
            pass
    empty = pd.DataFrame()
    for comp_t, fields in (
        (n.loads_t, ['p_set', 'p']),
        (n.generators_t, ['p_max_pu', 'p']),
        (n.lines_t, ['p0', 'p1', 'mu_upper', 'mu_lower']),
        (n.transformers_t, ['p0', 'p1', 'mu_upper', 'mu_lower']),
        (n.buses_t, ['marginal_price', 'p']),
    ):
        for f in fields:
            if hasattr(comp_t, f):
                setattr(comp_t, f, empty.copy())


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
    ap.add_argument('--force-recompute', action='store_true',
                    help='Overwrite existing status=ok rows via UPSERT; mutually '
                         'exclusive with --skip-existing')
    ap.add_argument('--chunk-size', type=int, default=6,
                    help='Snapshots per batched solve. 6 hits the sweet spot '
                         'for HiGHS PAMI on this LP; larger chunks blow up '
                         'simplex pivots.')
    args = ap.parse_args()

    if args.skip_existing and args.force_recompute:
        ap.error('--skip-existing and --force-recompute are mutually exclusive')

    start = parse_ts(args.start)
    end   = parse_ts(args.end)

    # Connect once for the lifetime of the loop
    conn = psycopg.connect(PG_DSN)

    # Load static reference data once
    log.info("Loading static reference data...")
    mc                   = pd.read_csv(MARGINAL_COSTS_CSV, index_col=0)
    bus_weather_zones    = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    gen_enriched         = pd.read_csv(GENERATOR_MATCHES_ENRICHED_CSV)

    # Single network instance for the lifetime of the process
    log.info("Initializing network + adapter...")
    n = pypsa.Network(NETWORK_NC)
    n.generators['marginal_cost'] = (
        n.generators.index.map(mc['marginal_cost']).fillna(0)
    )
    adapter = OperatingDataAdapter(conn, gen_enriched, bus_weather_zones, n)
    apply_static_mutations(
        n,
        line_derate=adapter.line_derate,
        tx_derate=adapter.tx_derate,
        outages=None,
    )

    # Optionally skip already-computed timestamps
    existing = set()
    if args.skip_existing:
        with conn.cursor() as cur:
            cur.execute("SELECT interval_ts FROM snapshot_meta WHERE status = 'ok'")
            existing = {row[0] for row in cur.fetchall()}
        log.info(f"Skip-existing: {len(existing)} timestamps already done")

    timestamps = [t for t in hourly_range(start, end) if t not in existing]
    n_total = len(timestamps)
    log.info(
        f"Processing {n_total} timestamps from {start} to {end} "
        f"in chunks of {args.chunk_size}"
    )

    counts = {'ok': 0, 'infeasible': 0, 'missing_data': 0, 'other_error': 0,
              'global_fallback': 0}
    t_start = time.time()
    i = 0

    for chunk_start in range(0, n_total, args.chunk_size):
        chunk = timestamps[chunk_start:chunk_start + args.chunk_size]
        if not chunk:
            continue

        log.info(
            f"compute_chunk [{chunk[0].isoformat()} .. {chunk[-1].isoformat()}] "
            f"({len(chunk)} ts)"
        )

        chunk_out = compute_chunk(chunk, adapter, n)

        for ts in chunk:
            status, result, op = chunk_out[ts]
            i += 1

            load_scaling_mode = (op or {}).get('meta', {}).get('load_scaling_mode')
            if load_scaling_mode == 'global_fallback':
                counts['global_fallback'] += 1

            try:
                if status == 'ok':
                    write_snapshot(conn, ts, result, op, n)
                    counts['ok'] += 1
                elif status == 'infeasible':
                    write_failure(conn, ts, 'infeasible', None,
                                  load_scaling_mode=load_scaling_mode)
                    counts['infeasible'] += 1
                elif status.startswith('missing_data'):
                    write_failure(conn, ts, 'missing_data', status,
                                  load_scaling_mode=load_scaling_mode)
                    counts['missing_data'] += 1
                else:
                    write_failure(conn, ts, 'error', status,
                                  load_scaling_mode=load_scaling_mode)
                    counts['other_error'] += 1
            except Exception as e:
                log.error(f"DB write failure at {ts}: {e}")
                conn.rollback()

        _clear_time_varying(n)
        gc.collect()

        elapsed = time.time() - t_start
        rate = i / elapsed if elapsed > 0 else 0
        eta = (n_total - i) / rate if rate > 0 else 0
        rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        log.info(
            f"[{i}/{n_total}] ok={counts['ok']} infeas={counts['infeasible']} "
            f"miss={counts['missing_data']} err={counts['other_error']} "
            f"global_sf={counts['global_fallback']}  "
            f"rate={rate:.2f}/s ETA={eta/60:.1f}min RSS={rss_mb:.0f} MB"
        )

    log.info(
        f"Done. {counts['ok']} ok, {counts['infeasible']} infeasible, "
        f"{counts['missing_data']} missing, {counts['other_error']} errors."
    )


if __name__ == '__main__':
    main()
