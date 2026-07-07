"""Hyperparameter sweep over (window-days, refit-days, ridge-lambda).

Invokes ``compute.implied_binding_proximity.runner`` for each grid combination
and summarizes per-run ``bp_ercot`` distribution + refit diagnostics into a
single table. Each run lands under its own ``runs/<run_id>/ibp/`` so results
are addressable and grep-able by run_id.

Panel loading is not reused across runs — every invocation re-queries
Postgres. Simple and slow; revisit if the grid grows.

Usage (runs inside the ``compute`` docker service; needs psycopg + db)::

    docker compose run --rm compute \\
      python -m compute.implied_binding_proximity.sweep_ibp \\
        --start 2025-01-01 --end 2025-12-31 \\
        [--window-days 60] [--refit-days 7,14] [--ridge-lambda 1e-3,1e-2,1e-1] \\
        [--out /compute/implied_binding_proximity/ibp_sweep_summary.csv]
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger("compute.implied_binding_proximity.sweep_ibp")

COMPUTE_DIR = Path(__file__).resolve().parent.parent
RUNS_ROOT = COMPUTE_DIR / "runs"

# Grids bracket the production defaults (see README "Trial findings").
DEFAULT_WINDOW_DAYS = "60"
DEFAULT_REFIT_DAYS = "7,14"
DEFAULT_RIDGE_LAMBDA = "1e-2,1e-1,1"
DEFAULT_STD_FLOOR = "50,100,200"
DEFAULT_MIN_BINDING_HOURS = "10,25,50"


def _ints(csv: str) -> list[int]:
    return [int(x) for x in csv.split(",") if x.strip()]


def _floats(csv: str) -> list[float]:
    return [float(x) for x in csv.split(",") if x.strip()]


def _run_id(
    window: int, refit: int, lam: float, std_floor: float, min_hours: int,
) -> str:
    return (
        f"ibp_sweep_w{window}_r{refit}_l{lam:g}"
        f"_s{std_floor:g}_h{min_hours}"
    )


def _invoke_runner(
    run_id: str, start: str, end: str,
    window: int, refit: int, lam: float, std_floor: float, min_hours: int,
) -> int:
    cmd = [
        sys.executable, "-m", "compute.implied_binding_proximity.runner",
        "--run-id", run_id,
        "--start", start, "--end", end,
        "--window-days", str(window),
        "--refit-days", str(refit),
        "--ridge-lambda", repr(lam),
        "--std-floor", repr(std_floor),
        "--min-binding-hours", str(min_hours),
    ]
    log.info("running %s", " ".join(cmd))
    return subprocess.run(cmd).returncode


def _summarize_run(
    run_id: str, window: int, refit: int, lam: float,
    std_floor: float, min_hours: int,
) -> dict | None:
    ibp_dir = RUNS_ROOT / run_id / "ibp"
    npz_path = ibp_dir / "bp_ercot.npz"
    if not npz_path.exists():
        log.warning("no bp_ercot.npz at %s; skipping", npz_path)
        return None
    with np.load(npz_path) as z:
        bp = z["bp_ercot"]

    r2_values: list[float] = []
    n_kept_values: list[int] = []
    n_sf_clipped_sum = 0
    for f in sorted(ibp_dir.glob("diagnostics_*.json")):
        with open(f) as fp:
            d = json.load(fp)
        if d.get("r2_overall") is not None:
            r2_values.append(float(d["r2_overall"]))
        n_kept_values.append(int(d.get("n_kept", 0)))
        n_sf_clipped_sum += int(d.get("n_sf_clipped", 0))

    flat = bp[np.isfinite(bp)]
    return {
        "run_id": run_id,
        "window_days": window,
        "refit_days": refit,
        "ridge_lambda": lam,
        "std_floor": std_floor,
        "min_binding_hours": min_hours,
        "mean_r2": float(np.mean(r2_values)) if r2_values else float("nan"),
        "median_n_kept": (
            float(np.median(n_kept_values)) if n_kept_values else float("nan")
        ),
        "bp_p95": float(np.quantile(flat, 0.95)) if flat.size else float("nan"),
        "bp_p99": float(np.quantile(flat, 0.99)) if flat.size else float("nan"),
        "bp_max": float(flat.max()) if flat.size else float("nan"),
        "n_sf_clipped": n_sf_clipped_sum,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--start", required=True,
                   help="Inclusive start date (YYYY-MM-DD).")
    p.add_argument("--end", required=True,
                   help="Exclusive end date (YYYY-MM-DD).")
    p.add_argument("--window-days", default=DEFAULT_WINDOW_DAYS,
                   help=f"Comma-separated window-days grid (default {DEFAULT_WINDOW_DAYS}).")
    p.add_argument("--refit-days", default=DEFAULT_REFIT_DAYS,
                   help=f"Comma-separated refit-days grid (default {DEFAULT_REFIT_DAYS}).")
    p.add_argument("--ridge-lambda", default=DEFAULT_RIDGE_LAMBDA,
                   help=f"Comma-separated ridge-lambda grid (default {DEFAULT_RIDGE_LAMBDA}).")
    p.add_argument("--std-floor", default=DEFAULT_STD_FLOOR,
                   help=f"Comma-separated std-floor grid (default {DEFAULT_STD_FLOOR}).")
    p.add_argument("--min-binding-hours", default=DEFAULT_MIN_BINDING_HOURS,
                   help=f"Comma-separated min-binding-hours grid (default {DEFAULT_MIN_BINDING_HOURS}).")
    p.add_argument("--out", type=Path, default=None,
                   help="CSV output path; prints to stdout if omitted.")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    windows = _ints(args.window_days)
    refits = _ints(args.refit_days)
    lambdas = _floats(args.ridge_lambda)
    floors = _floats(args.std_floor)
    min_hours_list = _ints(args.min_binding_hours)
    combos = [
        (w, r, lam, sf, mh)
        for w in windows for r in refits for lam in lambdas
        for sf in floors for mh in min_hours_list
    ]
    log.info(
        "sweep: %d combos over windows=%s refits=%s lambdas=%s "
        "std_floors=%s min_binding_hours=%s",
        len(combos), windows, refits, lambdas, floors, min_hours_list,
    )

    for window, refit, lam, floor, min_h in combos:
        run_id = _run_id(window, refit, lam, floor, min_h)
        rc = _invoke_runner(
            run_id, args.start, args.end,
            window, refit, lam, floor, min_h,
        )
        if rc != 0:
            log.error("runner failed for %s (rc=%d)", run_id, rc)

    rows: list[dict] = []
    for window, refit, lam, floor, min_h in combos:
        row = _summarize_run(
            _run_id(window, refit, lam, floor, min_h),
            window, refit, lam, floor, min_h,
        )
        if row is not None:
            rows.append(row)

    if not rows:
        log.error("no runs produced summarizable output")
        return 1

    df = pd.DataFrame(rows).sort_values("bp_max", ascending=False)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.out, index=False)
        log.info("wrote %s", args.out)
    else:
        with pd.option_context(
            "display.max_rows", None,
            "display.width", None,
            "display.max_columns", None,
        ):
            print(df.to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
