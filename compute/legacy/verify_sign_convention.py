"""
Verify the sign convention of modeled_congestion against a known binding case.

Loads a snapshot with a documented DFW-import binding line
(default: 2025-08-19T19:00), runs the OPF, picks the binding line with the
largest |shadow|, and reports the top buses by that line's per-bus contribution
to modeled_congestion under BOTH candidate sign conventions:

    μ_signed = +1 · (mu_lower − mu_upper)     ← current MU_SIGN in congestion.py
    μ_signed = −1 · (mu_lower − mu_upper)     ← flipped

PASS: the top bus (most positive contribution) sits in the north_central
weather zone under the current MU_SIGN. In a DFW summer-peak import-constrained
hour, that's where LMP is highest, so modeled_congestion should be positive on
those buses.

FAIL: if the flipped sign yields north_central at the top instead, edit
congestion.py::MU_SIGN and rerun this script. If neither sign yields
north_central at the top, the reference snapshot or the binding line does not
match the DFW-import scenario the plan assumes — pick a different reference
before locking a sign.

Usage:
    docker compose run --rm compute python /compute/verify_sign_convention.py
    docker compose run --rm compute python /compute/verify_sign_convention.py \
        --ts 2025-08-19T19:00 --top-k 10
"""
import argparse
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import psycopg
import pypsa

from config import (
    PG_DSN, NETWORK_NC,
    MARGINAL_COSTS_CSV, BUS_WEATHER_LOAD_ZONES_CSV, GENERATOR_MATCHES_ENRICHED_CSV,
)
from compute.legacy.congestion import MU_SIGN
from compute.legacy.operating_conditions import apply_static_mutations
from compute.legacy.operating_data_adapter import OperatingDataAdapter
from compute.legacy.ptdf_lodf import get_ptdf_lodf
from compute.legacy.snapshot import compute_snapshot_batch


REFERENCE_ZONE = 'north_central'


def _load_zone_map() -> pd.Series:
    bz = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    bz['zone'] = (bz['ercot_weather_zone']
                  .astype(str).str.lower().str.replace(' ', '_'))
    return bz.set_index(bz['name'].astype(str))['zone']


def _pick_binding_line(n: pypsa.Network, ts) -> tuple[str, float, float]:
    """Return (line_id, mu_signed_raw, |shadow|) for the largest-|shadow| line."""
    mu_up = n.lines_t.mu_upper.loc[ts].abs()
    mu_lo = n.lines_t.mu_lower.loc[ts].abs()
    shadow = (mu_up + mu_lo).reindex(n.lines.index).fillna(0)
    if (shadow <= 0.01).all():
        raise SystemExit(
            f"No binding lines at {ts}. Pick a different reference snapshot."
        )
    line_id = shadow.idxmax()
    mu_signed_raw = float(n.lines_t.mu_lower.loc[ts].get(line_id, 0.0)
                          - n.lines_t.mu_upper.loc[ts].get(line_id, 0.0))
    return line_id, mu_signed_raw, float(shadow.loc[line_id])


def _report_sign(
    label: str,
    sign: float,
    line_id: str,
    ptdf_row: np.ndarray,
    mu_signed_raw: float,
    sub_buses: list,
    zone_map: pd.Series,
    top_k: int,
) -> str:
    """Print the top-K buses under one sign convention. Return top bus's zone."""
    mu_signed = sign * mu_signed_raw
    contrib = pd.Series(ptdf_row * mu_signed, index=sub_buses,
                        name='mc_contrib')
    ordered = contrib.sort_values(ascending=False)

    top = ordered.head(top_k).to_frame()
    top['zone'] = pd.Series(top.index, index=top.index).astype(str).map(zone_map)

    print(f"\n[{label}] μ_signed = {sign:+.0f} · (mu_lower − mu_upper) "
          f"= {mu_signed:+.3f} $/MWh on line {line_id}")
    print(f"Top {top_k} buses by contribution to modeled_congestion "
          f"from this line alone:")
    print(top.round(4).to_string())

    top_bus = str(ordered.index[0])
    top_zone = zone_map.get(top_bus, '<unmapped>')
    return top_zone


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ts', default='2025-08-19T19:00',
                    help='UTC timestamp for the reference DFW-import hour')
    ap.add_argument('--top-k', type=int, default=10,
                    help='How many top buses to display under each sign')
    args = ap.parse_args()

    ts = datetime.fromisoformat(args.ts).replace(tzinfo=timezone.utc)

    mc_costs = pd.read_csv(MARGINAL_COSTS_CSV, index_col=0)
    bus_weather_zones = pd.read_csv(BUS_WEATHER_LOAD_ZONES_CSV)
    gen_enriched = pd.read_csv(GENERATOR_MATCHES_ENRICHED_CSV)
    zone_map = _load_zone_map()

    n = pypsa.Network(NETWORK_NC)
    n.generators['marginal_cost'] = (
        n.generators.index.map(mc_costs['marginal_cost']).fillna(0)
    )
    conn = psycopg.connect(PG_DSN)
    adapter = OperatingDataAdapter(conn, gen_enriched, bus_weather_zones, n)
    apply_static_mutations(
        n, line_derate=adapter.line_derate, tx_derate=adapter.tx_derate,
    )

    op = adapter.build(ts)
    results = compute_snapshot_batch(n, [ts], {ts: op})
    result = results[ts]
    if result['status'] != 'ok':
        raise SystemExit(f"OPF status != ok at {ts}: {result}")

    naive_ts = pd.Timestamp(ts).tz_convert('UTC').tz_localize(None)
    line_id, mu_signed_raw, shadow_mag = _pick_binding_line(n, naive_ts)
    line_row = n.lines.index.get_loc(line_id)

    ptdf, _lodf, sub_buses = get_ptdf_lodf(n)
    ptdf_row = ptdf[line_row]  # shape (n_sub_bus,)

    print(f"\n{'=' * 64}")
    print(f"Sign convention verification @ {ts.isoformat()}")
    print(f"{'=' * 64}")
    print(f"Binding line: {line_id}")
    print(f"|shadow| = |mu_upper| + |mu_lower| = {shadow_mag:.3f} $/MWh")
    print(f"Raw (mu_lower − mu_upper) at line = {mu_signed_raw:+.3f} $/MWh")
    print(f"Sub-network buses: {len(sub_buses)}")

    top_zone_pos = _report_sign(
        'current MU_SIGN=+1', +1.0, line_id, ptdf_row, mu_signed_raw,
        sub_buses, zone_map, args.top_k,
    )
    top_zone_neg = _report_sign(
        'flipped MU_SIGN=−1', -1.0, line_id, ptdf_row, mu_signed_raw,
        sub_buses, zone_map, args.top_k,
    )

    print(f"\n{'=' * 64}")
    print(f"Current congestion.MU_SIGN = {MU_SIGN:+.0f}")
    print(f"Reference zone (expected top): {REFERENCE_ZONE}")
    print(f"Top bus zone at MU_SIGN=+1: {top_zone_pos}")
    print(f"Top bus zone at MU_SIGN=−1: {top_zone_neg}")

    active_top_zone = top_zone_pos if MU_SIGN > 0 else top_zone_neg
    other_top_zone  = top_zone_neg if MU_SIGN > 0 else top_zone_pos

    if active_top_zone == REFERENCE_ZONE:
        print(f"\nPASS — current MU_SIGN={MU_SIGN:+.0f} yields "
              f"{REFERENCE_ZONE} at the top.")
        return 0

    if other_top_zone == REFERENCE_ZONE:
        print(f"\nFAIL — current MU_SIGN={MU_SIGN:+.0f} does NOT yield "
              f"{REFERENCE_ZONE} at the top, but the opposite sign does.")
        print(f"  → Edit compute/congestion.py: set MU_SIGN = "
              f"{-MU_SIGN:+.1f} and rerun this script.")
        raise SystemExit(1)

    print(f"\nINCONCLUSIVE — neither sign puts {REFERENCE_ZONE} at the top.")
    print(f"  The binding line ({line_id}) may not be a DFW-import line at "
          f"this snapshot. Pick a different --ts, or investigate the case.")
    raise SystemExit(2)


if __name__ == '__main__':
    raise SystemExit(main())
