"""Probe: within the shown overview set (top-N constraints x top-K nodes), how many
constraints does a typical displayed settlement point belong to? Decides whether a
node-hover membership popover is readable. (scratch, plan/0092-0001)
"""
from __future__ import annotations

import os
from collections import defaultdict

import numpy as np
import pandas as pd
import psycopg

RUN_ID = "map-v1"
DSN = (f"host={os.environ['PG_HOST']} dbname={os.environ['PG_DATABASE']} "
       f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")
TOP_N = 70   # constraints shown
TOP_K = 16   # nodes per constraint
MIN_FRAC = 0.15


def main():
    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("SELECT max(window_start) FROM implied_shift_factors WHERE run_id=%s", (RUN_ID,))
        ws = cur.fetchone()[0]
        cur.execute("SELECT constraint_key FROM constraint_geo WHERE run_id=%s AND window_start=%s "
                    "AND lat IS NOT NULL ORDER BY binding_hours DESC LIMIT %s", (RUN_ID, ws, TOP_N))
        keys = [r[0] for r in cur.fetchall()]

        member = defaultdict(list)  # sp -> [keys]
        for key in keys:
            cur.execute("SELECT settlement_point, sf FROM implied_shift_factors "
                        "WHERE run_id=%s AND window_start=%s AND constraint_key=%s "
                        "ORDER BY abs(sf) DESC", (RUN_ID, ws, key))
            rows = cur.fetchall()
            if not rows:
                continue
            peak = abs(rows[0][1])
            for spn, sf in rows[:TOP_K]:
                if abs(sf) < MIN_FRAC * peak:
                    break
                member[spn].append(key)

    counts = np.array([len(v) for v in member.values()])
    print(f"window {ws}  (top-{TOP_N} constraints, top-{TOP_K} nodes each)")
    print(f"distinct settlement points displayed: {len(member)}")
    print(f"memberships per displayed node: median {np.median(counts):.0f}, "
          f"mean {counts.mean():.1f}, p90 {np.percentile(counts,90):.0f}, max {counts.max()}")
    for thr in (1, 2, 3, 5, 8):
        print(f"  nodes in >= {thr} shown constraints: {(counts>=thr).sum():4d} "
              f"({100*(counts>=thr).mean():.0f}%)")


if __name__ == "__main__":
    main()
