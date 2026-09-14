"""Backfill canonical weekly SF artifacts from the retired relational store.

Run with ``--write`` only after reviewing the default dry report.  It processes
one map window at a time and is safe to resume.
"""
from __future__ import annotations

import argparse
import hashlib
import logging

import pandas as pd
import psycopg

from compute.projection.codecs import build_sf_window_artifact
from compute.sf_map.storage.maps import MAP_RUN_ID
from shared.settings import settings

log = logging.getLogger(__name__)


def _legacy_window(cur, run_id: str, window_start) -> pd.DataFrame:
    cur.execute(
        "SELECT constraint_key, settlement_point, sf FROM implied_shift_factors "
        "WHERE run_id = %s AND window_start = %s ORDER BY constraint_key, settlement_point",
        (run_id, window_start),
    )
    rows = cur.fetchall()
    if not rows:
        raise RuntimeError(f"legacy SF window is empty: {run_id} {window_start}")
    frame = pd.DataFrame(rows, columns=["key", "sp", "sf"])
    return frame.pivot(index="key", columns="sp", values="sf").fillna(0.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--write", action="store_true", help="persist artifacts after reporting")
    parser.add_argument("--backfill-provenance", action="store_true",
                        help="also infer missing daily-artifact map provenance")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    with psycopg.connect(settings.pg_dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT window_start FROM sf_window_meta WHERE run_id = %s ORDER BY window_start",
                    (args.run_id,))
        windows = [row[0] for row in cur.fetchall()]
        for window_start in windows:
            cur.execute("SELECT 1 FROM sf_window_artifact WHERE run_id = %s AND window_start = %s",
                        (args.run_id, window_start))
            if cur.fetchone() is not None:
                continue
            sf = _legacy_window(cur, args.run_id, window_start)
            blob = build_sf_window_artifact(sf)
            log.info("window=%s rows=%d shape=%s sha256=%s compressed=%d",
                     window_start, sf.size, sf.shape, hashlib.sha256(blob).hexdigest(), len(blob))
            if args.write:
                cur.execute(
                    "INSERT INTO sf_window_artifact (run_id, window_start, sf_npz) VALUES (%s, %s, %s)",
                    (args.run_id, window_start, blob),
                )
        if args.write:
            conn.commit()
        if args.backfill_provenance:
            cur.execute(
                "SELECT run_id, delivery_date, horizon FROM forecast_sf_artifact "
                "WHERE sf_map_run_id IS NULL ORDER BY delivery_date, horizon"
            )
            for forecast_run, delivery_date, horizon in cur.fetchall():
                cur.execute(
                    "SELECT window_start, window_end FROM sf_window_meta "
                    "WHERE run_id = %s AND window_end <= %s ORDER BY window_start DESC LIMIT 1",
                    (MAP_RUN_ID, delivery_date),
                )
                matches = cur.fetchall()
                if len(matches) != 1:
                    log.error("unproven provenance forecast=%s day=%s horizon=%s matches=%d",
                              forecast_run, delivery_date, horizon, len(matches))
                    continue
                window_start, window_end = matches[0]
                log.info("provenance forecast=%s day=%s horizon=%s map=%s window=[%s,%s)",
                         forecast_run, delivery_date, horizon, MAP_RUN_ID, window_start, window_end)
                if args.write:
                    cur.execute(
                        "UPDATE forecast_sf_artifact SET sf_map_run_id = %s, sf_window_start = %s, "
                        "sf_window_end = %s WHERE run_id = %s AND delivery_date = %s AND horizon = %s",
                        (MAP_RUN_ID, window_start, window_end, forecast_run, delivery_date, horizon),
                    )
            if args.write:
                conn.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
