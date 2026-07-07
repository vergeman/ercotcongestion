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

Usage::

    python -m compute.implied_binding_proximity.runner \
        --run-id <id> \
        --start 2025-05-24 --end 2025-07-23 \
        [--window-days 60] [--refit-days 7]
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
from .fit import MIN_BINDING_HOURS, RIDGE_LAMBDA
from .panels import load_congestion_panel, load_shadow_prices
from .rolling import RefitWindow, rolling_bp

log = logging.getLogger("compute.implied_binding_proximity.runner")

BASE_DIR = Path(__file__).parent
RUNS_ROOT = BASE_DIR.parent / "runs"

DEFAULT_WINDOW_DAYS = 60
DEFAULT_REFIT_DAYS = 7
DEFAULT_REF_METHOD = "system_lambda"


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
    p.add_argument("--ref-method", default=DEFAULT_REF_METHOD,
                   help=f"Reference-price method for the congestion input "
                        f"(default {DEFAULT_REF_METHOD}). Only system_lambda "
                        f"is compatible with the distributed-slack SF fit.")
    p.add_argument("--no-standardize", dest="standardize", action="store_false",
                   help="Skip per-column standardization of M before the ridge "
                        "solve (default: on).")
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

    def on_refit(window: RefitWindow) -> None:
        # Skip diagnostic emission for refit boundaries whose score period
        # falls entirely outside the requested range.
        if window.score_end <= start_ts:
            return
        _write_diagnostics(out_dir, args.run_id, window, args.min_binding_hours)
        r2 = refit_diagnostics(
            window.M_window, window.C_window, window.SF, args.min_binding_hours,
        )["r2_overall"]
        log.info(
            "refit window=[%s,%s) score=[%s,%s) n_kept=%d n_dropped=%d r2=%s",
            window.window_start.date(), window.window_end.date(),
            window.score_start.date(), window.score_end.date(),
            int((window.M_window > 0).sum().ge(args.min_binding_hours).sum()),
            int((window.M_window > 0).sum().lt(args.min_binding_hours).sum()),
            f"{r2:.3f}" if r2 is not None else "nan",
        )

    bp = rolling_bp(
        M, C,
        window_days=args.window_days,
        refit_days=args.refit_days,
        lam=args.ridge_lambda,
        min_hours=args.min_binding_hours,
        standardize=args.standardize,
        on_refit_window=on_refit,
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
