"""Measure NP1-346 outage-MW crosswalk coverage before enabling the feature."""
from __future__ import annotations

import argparse
import logging

import pandas as pd

from compute.mu_forecast.outage.crosswalk import GATE_C_BUILD, GATE_C_DEAD, coverage, load_crosswalk, verdict
from compute.probes.outage_feed import archive_index, fetch_report, settlement_points


def _sample_docs(idx: pd.DataFrame, n: int) -> pd.DataFrame:
    """Select the newest and evenly spaced historical archive snapshots."""
    if n >= len(idx):
        return idx
    pos = sorted({int(round(i)) for i in
                  pd.Series(range(n)).mul((len(idx) - 1) / (n - 1))})
    return idx.iloc[pos]


def main(argv: list[str] | None = None) -> int:
    from ErcotClient import ErcotClient

    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--snapshots", type=int, default=6,
                   help="Archive snapshots to score, spread across the backtest.")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    xwalk = load_crosswalk()
    sp_universe = settlement_points()
    print(f"\n=== NP1-346 crosswalk — Gate C (by outage MW) ===")
    print(f"  registry: {len(xwalk.unitcode_to_sp)} unit codes, "
          f"{len(xwalk.substation_to_sp)} unambiguous substations")
    print(f"  SF-map SP universe (ercot_dam_spp): {len(sp_universe)}")
    print(f"  Bar: >={GATE_C_BUILD:.0%} BUILD / {GATE_C_DEAD:.0%}-{GATE_C_BUILD:.0%} "
          f"flagged / <{GATE_C_DEAD:.0%} DEAD\n")

    client = ErcotClient()
    idx = archive_index(client)
    sample = _sample_docs(idx, args.snapshots)
    pooled_total = pooled_located = 0.0
    for _, doc in sample.iterrows():
        report = coverage(fetch_report(client, doc["docId"]), xwalk, sp_universe)
        pooled_total += report["total_mw"]
        pooled_located += report["located_mw"]
        methods = "  ".join(f"{k} {v:.0%}" for k, v in sorted(
            report["by_method"].items(), key=lambda item: -item[1]))
        print(f"  {doc['posted'].date()}  {report['rate']:6.1%} of "
              f"{report['total_mw']:8,.0f} MW  ({report['row_rate']:.0%} rows, "
              f"{report['n_sps']} SPs)   {methods}")

    rate = pooled_located / pooled_total if pooled_total else 0.0
    tag, action = verdict(rate)
    print(f"\n  POOLED: {rate:.1%} of {pooled_total:,.0f} MW located across "
          f"{len(sample)} snapshots")
    print(f"  GATE C: {rate:.1%} -> **{tag}** — {action}")
    newest = coverage(fetch_report(client, idx.iloc[-1]["docId"]), xwalk, sp_universe)
    if len(newest["unlocated"]):
        print("\n  biggest UNLOCATED resources by MW (newest snapshot):")
        for key, value in newest["unlocated"].head(10).items():
            print(f"    {str(key):<20} {value:>8,.0f} MW")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
