"""End-to-end pipeline orchestrator.

Single composition layer over the four `--run-id`-aware stage CLIs:

    congestion -> ercot -> matrix -> clustering

Each stage is invoked as a subprocess (cheaper than refactoring stage scripts
into importable libraries this sprint). Stages are skipped when their primary
output already exists, unless `--force` is set.

Usage::

    python -m compute.run_pipeline \
        --run-id <name> \
        --dates-file compute/sample_specs/reference_dates.json \
        [--ref-methods hub_avg,system_lambda_kkt,...] \
        [--algos hierarchical_corr,kmeans_vec,pca_kmeans] \
        [--ks 4,6,8,10,12,16] \
        [--records-output {gz,json,none}]  # default gz
        [--skip-completed]                 # default true
        [--force]                          # rerun everything
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from config import PG_DSN

BASE_DIR = Path(__file__).parent
RUNS_ROOT = BASE_DIR / "runs"
DEFAULT_DATES_FILE = Path("/compute/sample_specs/reference_dates.json")

STAGES = ("congestion", "ercot", "matrix", "clustering")


def _git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=BASE_DIR.parent, capture_output=True, text=True, check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_meta(meta_path: Path, meta: dict) -> None:
    tmp = meta_path.with_suffix(meta_path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(meta, f, indent=2, sort_keys=False)
    tmp.replace(meta_path)


def _initial_meta(run_id: str, dates_file: Path) -> dict:
    return {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "dates_file": str(dates_file),
        "dates_file_sha256": _sha256(dates_file),
        "stages": {s: {"status": "pending"} for s in STAGES},
    }


def _list_arg(s: str | None) -> list[str] | None:
    if s is None:
        return None
    return [tok.strip() for tok in s.split(",") if tok.strip()]


def _load_dates(dates_file: Path) -> list[datetime]:
    """Return a sorted, de-duplicated list of UTC timestamps from a dates file.

    Accepts either a flat list of ISO strings or a {regime: [iso]} dict — the
    same two shapes the stage runners accept.
    """
    with open(dates_file, "r") as f:
        raw = json.load(f)
    if isinstance(raw, list):
        flat = list(raw)
    elif isinstance(raw, dict):
        flat = [ts for ts_list in raw.values() for ts in ts_list]
    else:
        raise ValueError(
            f"{dates_file}: expected list[str] or dict[str, list[str]], "
            f"got {type(raw).__name__}"
        )
    out: list[datetime] = []
    seen: set[datetime] = set()
    for s in flat:
        ts = datetime.fromisoformat(s)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts in seen:
            continue
        seen.add(ts)
        out.append(ts)
    out.sort()
    return out


def _missing_snapshots(timestamps: list[datetime]) -> list[datetime]:
    """Return timestamps that have no row in bus_snapshots."""
    if not timestamps:
        return []
    with psycopg.connect(PG_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT interval_ts FROM bus_snapshots "
                "WHERE interval_ts = ANY(%s)",
                (timestamps,),
            )
            present = {row[0] for row in cur.fetchall()}
    return [ts for ts in timestamps if ts not in present]


def _ingest_hint(missing: list[datetime]) -> str:
    """Suggested write_snapshots.py invocation covering [min, max] of missing ts."""
    lo = min(missing).strftime("%Y-%m-%dT%H")
    hi = max(missing).strftime("%Y-%m-%dT%H")
    return (
        "docker compose run --rm compute python /compute/write_snapshots.py "
        f"--start {lo} --end {hi}"
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="python -m compute.run_pipeline",
        description=__doc__.splitlines()[0],
    )
    ap.add_argument("--run-id", required=True,
                    help="Run identifier; outputs land under compute/runs/<run_id>/.")
    ap.add_argument("--dates-file", type=Path, default=DEFAULT_DATES_FILE,
                    help=f"JSON file: flat list of ISO ts OR dict {{regime: [iso]}}. "
                         f"Default: {DEFAULT_DATES_FILE}.")
    ap.add_argument("--ref-methods", default=None,
                    help="Comma list passed to matrix --ref-methods. Default: all.")
    ap.add_argument("--algos", default=None,
                    help="Comma list passed to clustering --algos. Default: all five.")
    ap.add_argument("--ks", default=None,
                    help="Comma list of ints passed to clustering --ks. Default: 4,6,8,10,12,16.")
    ap.add_argument("--records-output", choices=("gz", "json", "none"), default="gz",
                    help="Per-record output format for congestion stages. "
                         "'none' keeps gz on disk but deletes them after matrix "
                         "exits ok (default: gz).")
    ap.add_argument("--skip-completed", dest="skip_completed",
                    action="store_true", default=True,
                    help="Skip stages whose primary output already exists (default: on).")
    ap.add_argument("--no-skip-completed", dest="skip_completed",
                    action="store_false",
                    help="Disable skip-completed behavior.")
    ap.add_argument("--force", action="store_true",
                    help="Rerun every stage even if its output exists.")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not args.dates_file.exists():
        print(f"dates file not found: {args.dates_file}", file=sys.stderr)
        return 2

    run_dir = RUNS_ROOT / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Copy dates file into run dir (provenance).
    dates_copy = run_dir / "reference_dates.json"
    if not dates_copy.exists() or _sha256(args.dates_file) != _sha256(dates_copy):
        shutil.copyfile(args.dates_file, dates_copy)

    meta_path = run_dir / "meta.json"
    meta = _initial_meta(args.run_id, args.dates_file)
    _write_meta(meta_path, meta)

    print(f"run_id={args.run_id}")
    print(f"run_dir={run_dir}")
    print(f"git_sha={meta['git_sha']}")
    print(f"dates_file_sha256={meta['dates_file_sha256']}")

    # Pre-flight: every dates-file timestamp must have a bus_snapshots row.
    timestamps = _load_dates(args.dates_file)
    print(f"pre-flight: checking {len(timestamps)} timestamps against bus_snapshots")
    missing = _missing_snapshots(timestamps)
    if missing:
        print(
            f"\n{len(missing)} timestamp(s) absent from bus_snapshots:",
            file=sys.stderr,
        )
        for ts in missing:
            print(f"  {ts.isoformat()}", file=sys.stderr)
        print(
            "\nIngest first (covers [min, max] of the missing set):\n"
            f"  {_ingest_hint(missing)}",
            file=sys.stderr,
        )
        return 3
    print("pre-flight: ok")

    return 0


if __name__ == "__main__":
    sys.exit(main())
