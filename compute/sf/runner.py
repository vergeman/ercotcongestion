"""CLI for the implied-binding-proximity stage.

Reads NP4-191-CD shadow prices and DAM SPP congestion for the requested date
range, fits ``C ≈ −M · SFᵀ`` on a rolling window (refit every
``--refit-days``), and writes

    runs/<run_id>/ibp/bp_ercot.npz         # bp_ercot[hour, sp]
    runs/<run_id>/ibp/diagnostics_YYYYMMDD.json   # per-refit-window

Reference-price method is fixed at ``system_lambda`` (NP4-523-CD) —
distributed-slack, comparable to the model-side distributed-slack PTDFs from
CM.7 / plan 0057. Other refs would need per-hour hub/load state that isn't
required here.

Output shape choice: npz, keyed off ``run_id`` under ``runs/<run_id>/ibp/``,
mirrors ``compute.matrix`` and ``compute.clustering.runner``. bp_ercot is a
function of the fit hyperparameters (window, refit cadence, ridge λ, etc.)
so persisting to a DB column would either overwrite prior sweeps or need
every param in the primary key. Per-run on-disk keeps sweep results
addressable without design lock-in.

DB persistence: pass ``--persist`` to also write the panel into
``implied_binding_proximity`` (keyed by ``run_id``) so the API can serve it.
Add ``--promote`` to flip ``implied_binding_proximity_current[layer]`` at
the same time. Sweeps leave both flags off and stay on-disk-only. To
backfill an npz already on disk without refitting, use
``compute.sf.ingest`` — it shares the same
``persist.py`` helpers.

SF matrix persistence: pass ``--persist-sf`` (independent of ``--persist``)
to also write the per-refit ``SF`` matrix into ``implied_shift_factors`` and
one row per refit into ``sf_window_meta``, keyed by ``run_id``. Entries below
``--sf-threshold`` are dropped. This is what downstream v3 surfaces read;
``bp_ercot`` (scalar) is unaffected.

Usage (runs inside the ``compute`` docker service; needs psycopg + db)::

    docker compose run --rm compute \
      python -m compute.sf.runner \
        --run-id <id> \
        --start 2025-05-24 --end 2025-07-23 \
        [--window-days 60] [--refit-days 7] \
        [--persist [--promote]]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import psycopg

from compute.config import PG_DSN

from .diagnostics import diagnostics_filename, refit_diagnostics
from .fit import MIN_BINDING_HOURS, RIDGE_LAMBDA, STD_FLOOR
from .panels import load_congestion_panel, load_shadow_prices
from .persist import (
    DEFAULT_LAYER,
    check_ref_method,
    copy_bp_rows,
    copy_sf_rows,
    delete_run,
    delete_sf_run,
    set_current_pointer,
    write_window_meta,
)
from .rolling import RefitWindow, rolling_bp

log = logging.getLogger("compute.sf.runner")

BASE_DIR = Path(__file__).parent
RUNS_ROOT = BASE_DIR.parent / "runs"

# NOTE: the honest OOS re-sweep (plan/0082 S1.5) selects window=240 (with
# λ=1.0, see fit.RIDGE_LAMBDA). Left at 60 here; adopt at S5 (promote a real run).
DEFAULT_WINDOW_DAYS = 60
DEFAULT_REFIT_DAYS = 7
DEFAULT_REF_METHOD = "system_lambda"
DEFAULT_SF_THRESHOLD = 1e-3


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _dates_from_run(run_dir: Path) -> tuple[date, date]:
    """Derive [start, end) from the run's reference_dates.json copy."""
    dates_path = run_dir / "reference_dates.json"
    if not dates_path.exists():
        raise SystemExit(
            f"{dates_path} not found; pass --start and --end explicitly, "
            f"or run compute.run_pipeline first to seed the run directory."
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
        **refit_diagnostics(window.M_window, window.C_window, window.SF, min_hours),
    }
    path = out_dir / diagnostics_filename(window.score_start)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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
    p.add_argument("--persist", action="store_true",
                   help="Write the panel to implied_binding_proximity under "
                        "this run_id. Makes the run available in the DB but "
                        "does NOT change what the API serves.")
    p.add_argument("--promote", action="store_true",
                   help="Point implied_binding_proximity_current[--layer] at "
                        "this run_id so the API starts serving it. Requires "
                        "--persist (no-op otherwise).")
    p.add_argument("--layer", default=DEFAULT_LAYER,
                   help=f"Map layer --promote flips (default {DEFAULT_LAYER}).")
    p.add_argument("--persist-sf", action="store_true",
                   help="Write the per-refit SF matrix to implied_shift_factors "
                        "(+ sf_window_meta) under this run_id. Independent of "
                        "--persist; the bp path is unaffected either way.")
    p.add_argument("--sf-threshold", type=float, default=DEFAULT_SF_THRESHOLD,
                   help=f"With --persist-sf, drop SF entries with |sf| below "
                        f"this (default {DEFAULT_SF_THRESHOLD}). The matrix is "
                        f"dense but mostly negligible; this keeps row counts sane.")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    run_dir = RUNS_ROOT / args.run_id
    out_dir = run_dir / "ibp"
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

    log.info(
        "loading panels: read=[%s, %s), score=[%s, %s), ref=%s",
        read_start, end, start, end, args.ref_method,
    )
    with psycopg.connect(PG_DSN) as conn:
        M = load_shadow_prices(conn, read_start, end)
        C = load_congestion_panel(conn, read_start, end, ref_method=args.ref_method)

    if M.empty or C.empty:
        log.error(
            "empty panel(s): shadow_prices=%s, congestion=%s. Ingest "
            "NP4-191-CD and NP4-190-CD for the requested range first.",
            M.shape, C.shape,
        )
        return 3
    log.info("M=%s, C=%s", M.shape, C.shape)

    # Panel index is tz-aware (Postgres TIMESTAMPTZ); match tz on all
    # boundary comparisons so we don't hit naive-vs-aware TypeErrors.
    panel_tz = M.index.tz if hasattr(M.index, "tz") else None
    start_ts = datetime.combine(start, datetime.min.time()).replace(tzinfo=panel_tz)
    end_ts = datetime.combine(end, datetime.min.time()).replace(tzinfo=panel_tz)

    # SF persistence (S0b) streams each refit window to the DB as it's fit,
    # inside one transaction opened before the fit loop and committed after.
    # This keeps memory flat (no buffering ~52 dense SF matrices) and shares
    # the on_refit callback that already carries SF.
    sf_conn = None
    sf_stats = {"windows": 0, "rows": 0}
    if args.persist_sf:
        check_ref_method(args.ref_method)
        sf_conn = psycopg.connect(PG_DSN)
        n_sf, n_meta = delete_sf_run(sf_conn, args.run_id)
        log.info(
            "cleared %d prior SF rows / %d meta rows for run_id=%s",
            n_sf, n_meta, args.run_id,
        )

    def on_refit(window: RefitWindow) -> None:
        # Skip diagnostic emission for refit boundaries whose score period
        # falls entirely outside the requested range.
        if window.score_end <= start_ts:
            return
        _write_diagnostics(out_dir, args.run_id, window, args.min_binding_hours)
        binding = (window.M_window > 0).sum()
        n_kept = int(binding.ge(args.min_binding_hours).sum())
        n_dropped = int(binding.lt(args.min_binding_hours).sum())
        n_clipped = int(window.SF.attrs.get("n_clipped", 0))
        r2 = refit_diagnostics(
            window.M_window, window.C_window, window.SF, args.min_binding_hours,
        )["r2_overall"]
        log.info(
            "refit window=[%s,%s) score=[%s,%s) n_kept=%d n_dropped=%d n_sf_clipped=%d r2=%s",
            window.window_start.date(), window.window_end.date(),
            window.score_start.date(), window.score_end.date(),
            n_kept, n_dropped, n_clipped,
            f"{r2:.3f}" if r2 is not None else "nan",
        )
        if sf_conn is not None:
            ws = window.window_start.isoformat()
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

    bp = rolling_bp(
        M, C,
        window_days=args.window_days,
        refit_days=args.refit_days,
        lam=args.ridge_lambda,
        min_hours=args.min_binding_hours,
        standardize=args.standardize,
        std_floor=args.std_floor,
        on_refit_window=on_refit,
    )

    if sf_conn is not None:
        sf_conn.commit()
        sf_conn.close()
        log.info(
            "persisted SF: %d windows, %d rows into implied_shift_factors",
            sf_stats["windows"], sf_stats["rows"],
        )

    # Trim to the requested [start, end) — the read window pulled extra
    # trailing history to warm up the first refit.
    if not bp.empty:
        bp = bp.loc[(bp.index >= start_ts) & (bp.index < end_ts)]

    if bp.empty:
        log.error("no bp_ercot rows produced in [%s, %s)", start, end)
        return 4

    out_path = out_dir / "bp_ercot.npz"
    # savez_compressed auto-appends .npz if missing, which confuses an
    # atomic .tmp swap; open the tmp file explicitly so it lands where we say.
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        np.savez_compressed(
            f,
            hours=np.array([ts.isoformat() for ts in bp.index], dtype=str),
            settlement_points=np.array(bp.columns.astype(str), dtype=str),
            bp_ercot=bp.to_numpy(dtype=float),
            params=np.array(json.dumps({
                "window_days": args.window_days,
                "refit_days": args.refit_days,
                "min_binding_hours": args.min_binding_hours,
                "ridge_lambda": args.ridge_lambda,
                "std_floor": args.std_floor,
                "ref_method": args.ref_method,
                "standardize": bool(args.standardize),
                "start": start.isoformat(),
                "end": end.isoformat(),
            }), dtype=str),
        )
    tmp.replace(out_path)
    log.info(
        "wrote %s: hours=%d SPs=%d", out_path, bp.shape[0], bp.shape[1],
    )

    if args.persist:
        # Fail fast if the ref method won't be DB-compatible, before we open
        # a connection or wipe prior rows.
        check_ref_method(args.ref_method)
        with psycopg.connect(PG_DSN) as conn:
            n_deleted = delete_run(conn, args.run_id)
            log.info("cleared %d prior rows for run_id=%s", n_deleted, args.run_id)
            n_rows = copy_bp_rows(
                conn, args.run_id,
                [ts.isoformat() for ts in bp.index],
                bp.columns.astype(str).tolist(),
                bp.to_numpy(dtype=float),
            )
            log.info("copied %d rows into implied_binding_proximity", n_rows)
            if args.promote:
                set_current_pointer(conn, args.layer, args.run_id)
                log.info("promoted layer=%s -> run_id=%s", args.layer, args.run_id)
            conn.commit()
    elif args.promote:
        log.warning("--promote is a no-op without --persist; ignoring")

    return 0


if __name__ == "__main__":
    sys.exit(main())
