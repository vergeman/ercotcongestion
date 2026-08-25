"""Backfill the per-day SF+μ artifact over a date range (runbook Step 4, looped).

For each CT delivery date in ``[--start, --end]`` this refits the daily μ heads and
writes that day's ``forecast_nodal`` rows + ``forecast_sf_artifact`` blob through the
SAME ``forecast_day``/``persist_forecast`` path the live daily job uses — so a
backfilled day is production-equivalent (byte-identical to what the live job would
have emitted, and it REPLACES any cheaper ``backfill_nodal`` rows for that day). This
is what lights up the constraint-explorer panel (``/map/constraints/ranked``) over
history; ``backfill_nodal`` fills prices but never writes this artifact.

Much heavier than ``backfill_nodal``: that shares one weekly fit across 7 days; this
refits PER DAY (~16 GiB peak each), so it is built to run long and resume.

  Resumable — skips dates already in ``forecast_sf_artifact`` (``--no-skip-existing``
              forces a rewrite), so an interrupted run picks up where it stopped.
  Fail-soft — a date missing complete DAM-close inputs or a causal map window is
              logged and skipped (``--stop-on-error`` aborts instead). Early dates
              with no causal map window are the common, expected skip.

  python -m compute.jobs.backfill_artifacts --run-id mu-all-v1 --map-run-id map-v1 \
      --start 2025-01-08 --end 2025-05-31 --to-db
"""
from __future__ import annotations

import argparse
import gc
import logging
import os
import time
from datetime import timedelta

import pandas as pd
import psycopg

from compute.jobs.daily_forecast import (
    arms_for,
    forecast_day,
    persist_forecast,
)
from compute.mu_forecast.model.runner import DEFAULT_TRAIN_DAYS
from compute.projection.sampling import N_DRAWS
from compute.sf_map.storage.maps import MAP_RUN_ID, MAX_SF_AGE_DAYS, MIN_SF_COVERAGE
from compute.time import normalize_ct_day

log = logging.getLogger("compute.jobs.backfill_artifacts")


def _dsn() -> str:
    return (f"host={os.environ['PG_HOST']} dbname={os.environ.get('PG_DB', 'ercot')} "
            f"user={os.environ['PG_USER']} password={os.environ['PG_PASSWORD']}")


def _fire_time_for(dd, horizon: int) -> pd.Timestamp:
    """The historical fire instant a live run would have had for delivery date
    `dd`, horizon `horizon` — the live cron's own schedule (0133), fed to
    `forecast_day`'s `vintage_cutoff` so a re-backfilled day reads only the
    covariate vintage that run could actually have seen.

    Final (h1): 17:00Z on D−1 — after D's DAM close, so the cap is a no-op; kept
    only so both tracks run one code path. Preview (h2): 20:15Z on D−2 — well
    before D's DAM close, so it genuinely restricts the read and keeps a
    re-backfilled preview a disadvantaged preview rather than a re-labeled final.
    """
    if horizon == 2:
        return pd.Timestamp(f"{dd - timedelta(days=2)} 20:15", tz="UTC")
    return pd.Timestamp(f"{dd - timedelta(days=1)} 17:00", tz="UTC")


def _existing_dates(dsn: str, run_id: str, horizon: int, lo, hi) -> set:
    """delivery_dates already holding a horizon's artifact for run_id in [lo, hi]
    — the skip set. Scoped to horizon (0123): a preview backfill's skip set must
    never be satisfied by the final's rows for the same day and vice versa."""
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT delivery_date FROM forecast_sf_artifact "
            "WHERE run_id = %s AND horizon = %s AND delivery_date BETWEEN %s AND %s",
            (run_id, horizon, lo.date(), hi.date()))
        return {r[0] for r in cur.fetchall()}


def _current_pointer(dsn: str) -> str | None:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT run_id FROM forecast_current WHERE layer = 'ercot'")
        row = cur.fetchone()
        return row[0] if row else None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--start", required=True, help="first CT delivery date (inclusive)")
    p.add_argument("--end", required=True, help="last CT delivery date (inclusive)")
    p.add_argument("--run-id", required=True)
    p.add_argument("--horizon", type=int, choices=(1, 2), default=1,
                   help="1 = final/t+1 (default); 2 = preview/t+2 — backfilled with "
                        "that day's real historical fire instant as the covariate "
                        "vintage cutoff, so it stays a genuinely disadvantaged "
                        "preview (0133). The two tracks are independent skip sets "
                        "and never clobber each other's rows (0123).")
    p.add_argument("--map-run-id", default=MAP_RUN_ID)
    p.add_argument("--to-db", action="store_true",
                   help="write forecast_nodal + forecast_sf_artifact per day; without "
                        "it every day is computed but nothing is written (dry run).")
    p.add_argument("--no-skip-existing", action="store_true",
                   help="recompute+rewrite dates already present in "
                        "forecast_sf_artifact (default skips them → resumable).")
    p.add_argument("--stop-on-error", action="store_true",
                   help="abort on the first failing date (default logs + skips it).")
    p.add_argument("--features", default="all")
    p.add_argument("--train-days", type=int, default=DEFAULT_TRAIN_DAYS)
    p.add_argument("--draws", type=int, default=N_DRAWS)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--preds", default=None,
                   help="residual pool .npz (default: the run's "
                        "runs/<run-id>/mu/mu_preds.npz)")
    p.add_argument("--npz-dir", default=None)
    p.add_argument("--max-sf-age-days", type=int, default=MAX_SF_AGE_DAYS)
    p.add_argument("--min-sf-coverage", type=float, default=MIN_SF_COVERAGE)
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")

    lo, hi = normalize_ct_day(args.start), normalize_ct_day(args.end)
    if hi < lo:
        p.error(f"--end {hi.date()} precedes --start {lo.date()}")
    # Calendar dates, not the tz-aware CT-midnight instants themselves: `lo`/`hi`
    # carry a UTC offset that changes across a DST transition, and stepping by
    # `freq="D"` on THOSE (fixed-offset) timestamps would silently drift off CT
    # midnight the day after the transition. Iterating tz-naive dates and letting
    # `forecast_day` normalizes each day's own CT-midnight
    # instant keeps every day exact (0133).
    days = pd.date_range(lo.date(), hi.date(), freq="D")
    arms = arms_for(args.features)
    dsn = _dsn()

    # persist_forecast flips forecast_current[ercot] to --run-id every day, so warn
    # loudly if that is not the promoted run — a backfill of the wrong run_id would
    # silently hijack the served pointer (runbook: "do not mix a different run ID").
    if args.to_db:
        current = _current_pointer(dsn)
        if current is not None and current != args.run_id:
            log.warning("forecast_current[ercot]=%s but backfilling run_id=%s — each "
                        "day will REPOINT the served run to %s. Ctrl-C now if wrong.",
                        current, args.run_id, args.run_id)

    skip = (set() if args.no_skip_existing
            else _existing_dates(dsn, args.run_id, args.horizon, lo, hi))
    if skip:
        log.info("%d of %d date(s) already have a horizon-%d artifact — skipping "
                 "(use --no-skip-existing to rewrite)",
                 len(skip), len(days), args.horizon)
    todo = [D for D in days if D.date() not in skip]

    log.info("backfilling SF+μ artifact for %d date(s) [%s → %s], run_id=%s "
             "horizon=%d%s",
             len(todo), lo.date(), hi.date(), args.run_id, args.horizon,
             "" if args.to_db else " (DRY RUN — nothing written)")

    written = failed = 0
    fail_dates: list = []
    t0 = time.perf_counter()
    for D in todo:
        dd = D.date()
        fire_time = _fire_time_for(dd, args.horizon)
        try:
            # Fresh connection per day: a per-day refit is minutes of CPU with no DB
            # traffic, long enough that a shared long-lived connection can be dropped
            # server-side mid-backfill. On any exception the `with` rolls back/closes.
            with psycopg.connect(dsn) as conn:
                result = forecast_day(
                    conn, D, run_id=args.run_id, horizon=args.horizon,
                    train_days=args.train_days,
                    arms=arms, seed=args.seed, n_draws=args.draws,
                    preds_path=args.preds, map_run_id=args.map_run_id,
                    max_sf_age_days=args.max_sf_age_days,
                    min_sf_coverage=args.min_sf_coverage,
                    fire_time=fire_time)
                if args.to_db:
                    persist_forecast(conn, result, npz_dir=args.npz_dir)
            del result
            gc.collect()          # release the ~16 GiB fit before the next day's peak
        except (RuntimeError, ValueError) as e:
            failed += 1
            fail_dates.append(dd)
            log.warning("  %s  SKIP — %s", dd, e)
            if args.stop_on_error:
                raise
            continue
        written += 1
        el = time.perf_counter() - t0
        eta = (el / written) * (len(todo) - written) / 60
        log.info("  %s  (%d/%d written, %d failed)  eta %.0fm",
                 dd, written, len(todo), failed, eta)

    log.info("done: %d written, %d skipped-existing, %d failed%s",
             written, len(skip), failed,
             (" — " + ", ".join(str(d) for d in fail_dates)) if fail_dates else "")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
