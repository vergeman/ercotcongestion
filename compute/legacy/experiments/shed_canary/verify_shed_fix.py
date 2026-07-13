"""
Canary verification for 0044/0049 shed adapter coverage fix.

Runs a shed-active snapshot with the fix in place and reports:
  * count of shed_* columns and their p_max_pu values (should be 1.0)
  * escaped-adapter-coverage warnings (should be zero)
  * comparison of load_shed_mw, hub LMPs, and reference prices vs the
    v1-120 baseline artefact (built with the pre-fix p_max_pu=0.8)

Usage:
    docker compose run --rm compute python /compute/experiments/shed_canary/verify_shed_fix.py
    docker compose run --rm compute python /compute/experiments/shed_canary/verify_shed_fix.py \
        --ts 2025-01-22T13:00
"""
import argparse
import gzip
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import psycopg
import pypsa

from config import (
    PG_DSN, NETWORK_NC,
    MARGINAL_COSTS_CSV, BUS_WEATHER_LOAD_ZONES_CSV, GENERATOR_MATCHES_ENRICHED_CSV,
)
from compute.legacy.constants import SHED_PREFIX
from compute.legacy.operating_conditions import apply_static_mutations
from compute.legacy.operating_data_adapter import OperatingDataAdapter
from compute.legacy.snapshot import compute_snapshot_batch


BASELINE = Path("/compute/runs/v1-120/congestion/model_results.json.gz")


class WarnCounter(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.records = []

    def emit(self, record):
        if "escaped adapter coverage" in record.getMessage():
            self.records.append(record.getMessage())


def load_baseline(ts_iso: str) -> dict | None:
    if not BASELINE.exists():
        return None
    with gzip.open(BASELINE, "rt") as f:
        data = json.load(f)
    for r in data:
        if r["ts"] == ts_iso:
            return r
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ts", default="2025-01-22T13:00")
    args = ap.parse_args()

    ts = datetime.fromisoformat(args.ts).replace(tzinfo=timezone.utc)

    counter = WarnCounter()
    logging.getLogger("operating_conditions").addHandler(counter)

    mc = pd.read_csv(MARGINAL_COSTS_CSV, index_col=0)
    bus_weather_zones = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    gen_enriched = pd.read_csv(GENERATOR_MATCHES_ENRICHED_CSV)

    n = pypsa.Network(NETWORK_NC)
    n.generators["marginal_cost"] = (
        n.generators.index.map(mc["marginal_cost"]).fillna(0)
    )
    conn = psycopg.connect(PG_DSN)
    adapter = OperatingDataAdapter(conn, gen_enriched, bus_weather_zones, n)
    apply_static_mutations(
        n, line_derate=adapter.line_derate, tx_derate=adapter.tx_derate,
    )

    op = adapter.build(ts)

    # Chunk 1: primes n with shed_ generators (added inside
    # compute_snapshot_batch → _ensure_load_shed_gens).
    _ = compute_snapshot_batch(n, [ts], {ts: op})

    # Chunk 2 exercises the actual bug path: shed_ gens are now in
    # n.generators.index, so the pre-fix code diffed them out of
    # per_gen.index and emitted 2,751 escaped-coverage warnings + set
    # p_max_pu to 0.8. Post-fix: partitioned into shed_missing, warning
    # suppressed, p_max_pu forced to 1.0.
    assert n.generators.index.str.startswith(SHED_PREFIX).sum() > 0, (
        "expected shed_* gens present after first batch"
    )
    counter.records.clear()
    results = compute_snapshot_batch(n, [ts], {ts: op})
    result = results[ts]

    naive_ts = pd.Timestamp(ts).tz_convert("UTC").tz_localize(None)
    pmax_row = n.generators_t.p_max_pu.loc[naive_ts]
    shed_mask = pmax_row.index.str.startswith(SHED_PREFIX)
    shed_pmax = pmax_row[shed_mask]
    nonshed_pmax = pmax_row[~shed_mask]

    print("=" * 68)
    print(f"Snapshot: {args.ts}   status={result['status']}")
    print("=" * 68)

    print(f"\n[p_max_pu on shed_ columns]")
    print(f"  shed columns:    {len(shed_pmax)}")
    print(f"  min:             {shed_pmax.min():.4f}")
    print(f"  max:             {shed_pmax.max():.4f}")
    print(f"  == 1.0 count:    {int((shed_pmax == 1.0).sum())} / {len(shed_pmax)}")
    print(f"  <  1.0 count:    {int((shed_pmax < 1.0).sum())}")

    print(f"\n[p_max_pu on non-shed columns]")
    print(f"  gens:            {len(nonshed_pmax)}")
    print(f"  min / max:       {nonshed_pmax.min():.3f} / {nonshed_pmax.max():.3f}")
    print(f"  mean:            {nonshed_pmax.mean():.3f}")

    print(f"\n[warnings]")
    print(f"  escaped adapter coverage: {len(counter.records)}")
    for msg in counter.records[:3]:
        print(f"    - {msg}")

    m = result["meta"]
    print(f"\n[snapshot meta]")
    print(f"  total_load_mw:      {m['total_load_mw']:>12,.1f}")
    print(f"  total_gen_mw:       {m['total_gen_mw']:>12,.1f}")
    print(f"  load_shed_total_mw: {m['load_shed_total_mw']:>12,.1f}")
    print(f"  n_shed_buses:       {m['n_shed_buses']:>12d}")
    print(f"  lmp mean/min/max:   {m['lmp_mean']:>8.2f} / {m['lmp_min']:>8.2f} / {m['lmp_max']:>8.2f}")
    print(f"  objective_cost:     ${m['objective_cost']:>14,.0f}")

    base = load_baseline(ts.isoformat())
    if base is None:
        print("\n[baseline] not found — skipping delta table")
        return

    print(f"\n[delta vs v1-120 baseline (pre-fix)]")
    print(f"  metric               baseline        post-fix        delta")
    print(f"  -------------------  --------------  --------------  ------------")
    def row(name, b, p, fmt=".2f"):
        if b is None or p is None:
            print(f"  {name:<20} {str(b):>14} {str(p):>14} {'--':>12}")
            return
        delta = p - b
        print(f"  {name:<20} {b:>14{fmt}} {p:>14{fmt}} {delta:>+12{fmt}}")

    row("load_shed_mw", base.get("load_shed_mw"), m["load_shed_total_mw"], ".1f")
    row("lmp_mean", base["lmp_summary"].get("mean"), m["lmp_mean"], ".2f")
    row("lmp_min", base["lmp_summary"].get("min"), m["lmp_min"], ".2f")
    row("lmp_max", base["lmp_summary"].get("max"), m["lmp_max"], ".2f")

    # Reference prices require snapshot_runner post-processing; not
    # computed here. The baseline values are recorded for context.
    b_refs = base.get("reference_prices", {})
    print("\n[baseline reference_prices for context — not recomputed]")
    for k in ("hub_avg", "load_weighted", "gen_weighted", "lmp_median"):
        v = b_refs.get(k)
        print(f"  {k:<16} {v if v is None else f'{v:>8.2f}'}")


if __name__ == "__main__":
    main()
