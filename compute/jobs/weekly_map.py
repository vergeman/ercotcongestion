"""CLI for the implied shift-factor (SF) stage.

Reads NP4-191-CD shadow prices and DAM SPP congestion for the requested date
range, fits ``C ≈ −M · SFᵀ`` on a rolling window (refit every ``--refit-days``),
and writes per-refit-window diagnostics to

    runs/<run_id>/sf/diagnostics_YYYYMMDD.json   # per-refit-window

Reference-price method is fixed at ``system_lambda``

SF matrix persistence: pass ``--persist-sf`` to write the per-refit ``SF``
matrix into ``implied_shift_factors`` and one row per refit into
``sf_window_meta``, keyed by ``run_id``. Entries below ``--sf-threshold`` are
dropped.

Incremental append (the default under ``--persist-sf``): a run fits and
persists only new refit boundaries

Pass ``--rebuild`` for an explicit full wipe + refit (the old
delete-then-rewrite behavior).

Usage (runs inside the ``compute`` docker service; needs psycopg + db)::

    docker compose run --rm compute \
      python -m compute.jobs.weekly_map \
        --run-id <id> \
        --start 2025-01-01 --end 2025-07-23 \
        [--window-days 240] [--refit-days 7] \
        --persist-sf [--rebuild]

"""
from __future__ import annotations

import argparse
import gc
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import psycopg

from shared.settings import settings

from compute.sf_map.config import (
    REFIT_DAYS as DEFAULT_REFIT_DAYS,
    WINDOW_DAYS as DEFAULT_WINDOW_DAYS,
)
from compute.sf_map.model.diagnostics import diagnostics_filename, refit_diagnostics
from compute.sf_map.model.fit import MIN_BINDING_HOURS, RIDGE_LAMBDA, STD_FLOOR
from compute.inputs.dam import (
    load_congestion_panel, load_shadow_prices, panel_bounds,
)
from compute.sf_map.storage.persist import (
    check_ref_method,
    copy_sf_rows,
    delete_sf_run,
    existing_sf_windows,
    write_window_meta,
)
from compute.sf_map.model.rolling import RefitWindow, fit_refit_window, rolling_sf

log = logging.getLogger("compute.jobs.weekly_map")

BASE_DIR = Path(__file__).parent
RUNS_ROOT = BASE_DIR.parent / "runs"

# Window/refit cadence come from `compute.sf_map.config`:
# window=240 / refit=7 with RIDGE_LAMBDA=1.0
DEFAULT_REF_METHOD = "system_lambda"
DEFAULT_SF_THRESHOLD = 1e-3


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _dates_from_run(run_dir: Path) -> tuple[date, date]:
    """Derive [start, end) from the run's reference_dates.json copy."""
    dates_path = run_dir / "reference_dates.json"
    if not dates_path.exists():
        raise SystemExit(
            f"{dates_path} not found; pass --start and --end explicitly."
        )
    with open(dates_path) as f:
        raw = json.load(f)
    if isinstance(raw, dict):
        flat = [ts for lst in raw.values() for ts in lst]
    else:
        flat = list(raw)
    if not flat:
        raise SystemExit(f"{dates_path} has no timestamps")
    parsed = sorted(datetime.fromisoformat(s) for s in flat)
    return parsed[0].date(), parsed[-1].date() + timedelta(days=1)


def _write_diagnostics(out_dir: Path, run_id: str, window: RefitWindow, min_hours: int) -> None:
    payload = {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_start": window.window_start.isoformat(),
        "window_end": window.window_end.isoformat(),
        "score_start": window.score_start.isoformat(),
        "score_end": window.score_end.isoformat(),
        # M_fit, not M_window: under grouping SF's rows are group keys, so the
        # panel whose columns match them is the aggregate. Same object when
        # ungrouped.
        **refit_diagnostics(window.M_fit, window.C_window, window.SF, min_hours),
    }
    path = out_dir / diagnostics_filename(window.score_start)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    # allow_abbrev=False so a stale `--persist` (a removed legacy flag) errors
    # rather than silently abbreviating to `--persist-sf`.
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0], allow_abbrev=False)
    p.add_argument("--run-id", required=True)
    p.add_argument("--start", type=_parse_date, default=None,
                   help="Inclusive start date (YYYY-MM-DD). Default: min "
                        "timestamp from the run's reference_dates.json.")
    p.add_argument("--end", type=_parse_date, default=None,
                   help="Exclusive end date (YYYY-MM-DD). Default: (max "
                        "timestamp from reference_dates.json) + 1 day.")
    p.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS,
                   help=f"Rolling fit window in days (default {DEFAULT_WINDOW_DAYS}).")
    p.add_argument("--refit-days", type=int, default=DEFAULT_REFIT_DAYS,
                   help=f"Days between successive refits (default "
                        f"{DEFAULT_REFIT_DAYS}, matching the doc's weekly "
                        f"cadence). 1 reproduces the prototype's daily behavior.")
    p.add_argument("--min-binding-hours", type=int, default=MIN_BINDING_HOURS,
                   help=f"Drop constraints binding fewer hours in the window "
                        f"(default {MIN_BINDING_HOURS}).")
    p.add_argument("--ridge-lambda", type=float, default=RIDGE_LAMBDA,
                   help=f"Ridge regularization strength (default {RIDGE_LAMBDA}).")
    p.add_argument("--std-floor", type=float, default=STD_FLOOR,
                   help=f"Lower bound on the per-column std used for "
                        f"standardization (default {STD_FLOOR}). Larger "
                        f"values suppress inflation on low-variance columns.")
    p.add_argument("--ref-method", default=DEFAULT_REF_METHOD,
                   help=f"Reference-price method for the congestion input "
                        f"(default {DEFAULT_REF_METHOD}). Only system_lambda "
                        f"is compatible with the distributed-slack SF fit.")
    p.add_argument("--no-standardize", dest="standardize", action="store_false",
                   help="Skip per-column standardization of M before the ridge "
                        "solve (default: on).")
    p.add_argument("--persist-sf", action="store_true",
                   help="Write the per-refit SF matrix to implied_shift_factors "
                        "(+ sf_window_meta) under this run_id. Incremental by "
                        "default: only new complete windows are fit + written.")
    p.add_argument("--rebuild", action="store_true",
                   help="With --persist-sf, wipe all SF/meta rows for this run_id "
                        "first, then refit + persist every complete window from "
                        "scratch. Omit for the default incremental append.")
    p.add_argument("--sf-threshold", type=float, default=DEFAULT_SF_THRESHOLD,
                   help=f"With --persist-sf, drop SF entries with |sf| below "
                        f"this (default {DEFAULT_SF_THRESHOLD}). The matrix is "
                        f"dense but mostly negligible; this keeps row counts sane.")
    p.add_argument("--chunk-weeks", type=int, default=32,
                   help="Load and fit this many refit windows at a time "
                        "(default 32). Bounds dense M/C pivots during rebuilds; "
                        "an incremental run loads only its new fit window. "
                        "Use 0 for the legacy full-history path.")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    run_dir = RUNS_ROOT / args.run_id
    out_dir = run_dir / "sf"
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.start is None or args.end is None:
        start_dt, end_dt = _dates_from_run(run_dir)
        start = args.start or start_dt
        end = args.end or end_dt
    else:
        start, end = args.start, args.end

    # Extend the read window backwards so the earliest refit can see its full
    # trailing history. Without this, the first ~window_days worth of refits
    # get truncated fits.
    read_start = start - timedelta(days=args.window_days)

    if args.chunk_weeks < 0:
        p.error("--chunk-weeks must be non-negative")

    # SF persistence streams each refit window to the DB as it's fit, inside
    # one transaction opened before the fit loop and committed after. This
    # keeps memory flat and shares the on_refit callback that already carries
    # SF.
    sf_conn = None
    sf_stats = {"windows": 0, "rows": 0}

    # window_start ns-instants already persisted for this run_id (ns: nanoseconds)
    existing_ns: set[int] = set()
    if args.persist_sf:
        check_ref_method(args.ref_method)      # reference-price method system lambda
        sf_conn = psycopg.connect(settings.pg_dsn)

        if args.rebuild:
            # Full wipe then refit every complete window. The delete shares the
            # fit loop's transaction (committed at the end), so the prior served
            # window survives a crash mid-rebuild.
            n_sf, n_meta = delete_sf_run(sf_conn, args.run_id)
            log.info(
                "--rebuild: cleared %d prior SF rows / %d meta rows for run_id=%s",
                n_sf, n_meta, args.run_id,
            )
        else:
            # { } set comprehension; where pd.Timestamp(ws).value turns ns to
            # epoch integer
            existing_ns = {
                pd.Timestamp(ws).value for ws in existing_sf_windows(sf_conn, args.run_id)
            }
            log.info(
                "incremental: %d window(s) already persisted for run_id=%s; "
                "fitting only new complete boundaries",
                len(existing_ns), args.run_id,
            )

    def on_refit(window: RefitWindow) -> None:
        # Skip diagnostic emission for refit boundaries whose score period
        # falls entirely outside the requested range.
        if window.score_end <= start_ts:
            return

        # json files: runs/<run_id>/sf/diagnostics_YYYYMMDD.json
        _write_diagnostics(out_dir, args.run_id, window, args.min_binding_hours)

        # binding stats
        binding = (window.M_fit > 0).sum()
        n_kept = int(binding.ge(args.min_binding_hours).sum())
        n_dropped = int(binding.lt(args.min_binding_hours).sum())
        n_clipped = int(window.SF.attrs.get("n_clipped", 0))

        r2 = refit_diagnostics(
            window.M_fit, window.C_window, window.SF, args.min_binding_hours,
        )["r2_overall"]

        log.info(
            "refit window=[%s,%s) score=[%s,%s) n_kept=%d n_dropped=%d n_sf_clipped=%d r2=%s",
            window.window_start.date(), window.window_end.date(),
            window.score_start.date(), window.score_end.date(),
            n_kept, n_dropped, n_clipped,
            f"{r2:.3f}" if r2 is not None else "nan",
        )

        if sf_conn is None:
            return

        # persist only complete windows
        if (window.score_end - window.score_start) != timedelta(days=args.refit_days):
            log.info(
                "skip incomplete tail: window_start=%s score=[%s,%s) < %dd",
                window.window_start.isoformat(), window.score_start.date(),
                window.score_end.date(), args.refit_days,
            )
            return

        # Belt-and-suspenders: skip_window_starts already prevents re-fitting an
        # already-persisted boundary, so this never triggers on the incremental
        # path — but it guarantees no re-COPY (no PK clash) if it ever did.
        if pd.Timestamp(window.window_start).value in existing_ns:
            return

        ws = window.window_start.isoformat()

        # copy here is postgres COPY to bulk "insert" the SF matrix
        n = copy_sf_rows(sf_conn, args.run_id, ws, window.SF, args.sf_threshold)

        write_window_meta(sf_conn, args.run_id, {
            "window_start": ws,
            "window_end": window.window_end.isoformat(),
            "score_start": window.score_start.isoformat(),
            "score_end": window.score_end.isoformat(),
            "n_kept": n_kept,
            "n_dropped": n_dropped,
            "n_sf_clipped": n_clipped,
            "fit_r2": r2,
        })
        sf_stats["windows"] += 1
        sf_stats["rows"] += n

    if args.chunk_weeks:

        # Discover the endpoints of the panel, then construct the exact same
        # fixed grid `rolling_sf` would.
        #
        # bounds: (lo, hi) datetime: queried min/max interval_ts
        #   from dam_shadow_prices union dam_system_lambda + dam_spp
        with psycopg.connect(settings.pg_dsn) as conn:
            bounds = panel_bounds(conn, read_start, end)

        if bounds is None:
            log.error("empty panel clock in [%s, %s)", read_start, end)
            return 3

        # date conversion
        first_hour, last_hour = bounds
        panel_tz = pd.Timestamp(first_hour).tz
        start_ts = datetime.combine(start, datetime.min.time()).replace(tzinfo=panel_tz)
        first_day = pd.Timestamp(first_hour).normalize()
        last_day = pd.Timestamp(last_hour).normalize()
        refit = pd.Timedelta(days=args.refit_days)
        window = pd.Timedelta(days=args.window_days)
        day = pd.Timedelta(days=1)

        #
        # score: this is a time period tied to refit - the forward component
        #
        # window_start                         score_start          score_end
        # │                                    │                    │
        # ├────── 240-day data used to fit ────┼──── final week ────┤
        # │                                    │                    │
        # └──────────────────── window_end = score_end ─────────────┘
        #
        # refit_starts: sequence of weekly (freq refit) start day timestamps
        refit_starts = pd.date_range(first_day, last_day, freq=refit, inclusive="left")
        if not len(refit_starts):
            refit_starts = pd.DatetimeIndex([first_day])
        pending: list[tuple[pd.Timestamp, pd.Timestamp]] = []

        for refit_start in refit_starts:
            score_end = min(refit_start + refit, last_day + day)
            window_start = score_end - window
            # omit loading a chunk rather than fitting work that cannot
            # produce a diagnostic or persisted row.
            if score_end <= start_ts:
                continue
            if window_start.value not in existing_ns:
                pending.append((refit_start, score_end))

        # chunk the collected valid refits pushed to pending above
        log.info("chunked fit: %d pending refit(s), %d week(s) per panel",
                 len(pending), args.chunk_weeks)

        for n in range(0, len(pending), args.chunk_weeks):
            chunk = pending[n:n + args.chunk_weeks]
            chunk_start = min(score_end - window for _, score_end in chunk)
            chunk_end = max(score_end for _, score_end in chunk)

            log.info("fit chunk %d/%d: windows [%s, %s)",
                     n // args.chunk_weeks + 1,
                     (len(pending) + args.chunk_weeks - 1) // args.chunk_weeks,
                     chunk_start.date(), chunk_end.date())
            with psycopg.connect(settings.pg_dsn) as conn:
                M = load_shadow_prices(conn, chunk_start, chunk_end)
                C = load_congestion_panel(conn, chunk_start, chunk_end,
                                          ref_method=args.ref_method)
            if M.empty or C.empty:
                log.error("empty panel chunk [%s, %s): M=%s C=%s",
                          chunk_start, chunk_end, M.shape, C.shape)
                return 3
            log.info("fit chunk M=%s, C=%s", M.shape, C.shape)

            try:
                for refit_start, score_end in chunk:
                    refitWindow = fit_refit_window(
                        M, C, refit_start=refit_start, score_end=score_end,
                        window_days=args.window_days, lam=args.ridge_lambda,
                        min_hours=args.min_binding_hours,
                        standardize=args.standardize, std_floor=args.std_floor,
                    )
                    on_refit(refitWindow)
            finally:
                del M, C
                gc.collect()
    else:
        log.info(
            "loading panels: read=[%s, %s), score=[%s, %s), ref=%s",
            read_start, end, start, end, args.ref_method,
        )
        with psycopg.connect(settings.pg_dsn) as conn:
            M = load_shadow_prices(conn, read_start, end)
            C = load_congestion_panel(conn, read_start, end,
                                      ref_method=args.ref_method)
        if M.empty or C.empty:
            log.error("empty panel(s): shadow_prices=%s, congestion=%s. Ingest "
                      "NP4-191-CD and NP4-190-CD for the requested range first.",
                      M.shape, C.shape)
            return 3
        log.info("M=%s, C=%s", M.shape, C.shape)
        panel_tz = M.index.tz if hasattr(M.index, "tz") else None
        start_ts = datetime.combine(start, datetime.min.time()).replace(tzinfo=panel_tz)
        rolling_sf(
            M, C,
            window_days=args.window_days,
            refit_days=args.refit_days,
            lam=args.ridge_lambda,
            min_hours=args.min_binding_hours,
            standardize=args.standardize,
            std_floor=args.std_floor,
            on_refit_window=on_refit,
            skip_window_starts=existing_ns,
        )

    if sf_conn is not None:
        sf_conn.commit()
        sf_conn.close()
        log.info(
            "persisted SF: %d windows, %d rows into implied_shift_factors",
            sf_stats["windows"], sf_stats["rows"],
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
