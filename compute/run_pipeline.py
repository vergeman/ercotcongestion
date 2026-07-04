"""End-to-end pipeline orchestrator.

Single composition layer over the `--run-id`-aware stage CLIs, in order:

    congestion -> ercot -> matrix
        -> correlation_map -> basis_regression -> cca   (CM.1–CM.3 mapping)
        -> clustering                                    (β-loading sweep)
        -> scorecard                                     (per-zone headline)

Each stage is invoked as a subprocess (cheaper than refactoring stage scripts
into importable libraries this sprint). Stages are skipped when their primary
output already exists, unless `--force` is set.

Ordering constraints:
  * `clustering` (default algo `hierarchical_on_beta`) reads the β-loading npz
    written by `basis_regression`, so mapping must precede clustering.
  * `scorecard` reads both the CM.1 correlation npz and the clustering
    labels npz for the chosen `(algo, K)`.

Usage::

    python -m compute.run_pipeline \
        --run-id <name> \
        --dates-file compute/sample_specs/reference_dates.json \
        [--ref-methods hub_avg,system_lambda_kkt,...] \
        [--algos hierarchical_on_beta,hybrid_geo,hierarchical_corr] \
        [--ks 4,6,8,10,12,16] \
        [--scorecard-algo hierarchical_on_beta] \
        [--scorecard-k 6] \
        [--records-output {gz,json,none}]  # default gz
        [--skip-completed]                 # default true
        [--force]                          # rerun everything
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
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
DEFAULT_COORDS_MODEL = Path(
    "/data/processed/Texas2k_series25_case1_summerpeak_bus_coords.csv"
)
DEFAULT_COORDS_ERCOT = Path("/data/processed/settlement_points_geocoded.csv")

STAGES = (
    "ercot",
    "matrix",
    "correlation_map",
    "basis_regression",
    "cca",
    "clustering",
    "scorecard",
)
TAIL_LINES = 80


def _git_sha() -> str | None:
    # Docker containers typically don't have git or the .git directory;
    # let the caller pass through via env var (e.g. -e GIT_SHA=$(git rev-parse HEAD)).
    env = os.environ.get("GIT_SHA")
    if env:
        return env.strip()
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


def _dir_size_human(path: Path) -> str:
    """Wall-clock summary of a run's on-disk footprint. Falls back to raw bytes
    if `du` is unavailable."""
    try:
        out = subprocess.run(
            ["du", "-sh", str(path)],
            capture_output=True, text=True, check=True,
        )
        return out.stdout.split(None, 1)[0]
    except (subprocess.CalledProcessError, FileNotFoundError):
        total = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
        return f"{total} B"


def _drop_per_record(run_dir: Path) -> None:
    """Delete per-record congestion JSONs after matrix consumes them.

    Used when --records-output=none. The matrix npz already carries the
    denormalized form forward; the per-record JSONs were only the
    audit-friendly intermediate.
    """
    cong_dir = run_dir / "congestion"
    if not cong_dir.exists():
        return
    deleted: list[Path] = []
    for stem in ("model_results", "ercot_results"):
        for ext in (".json", ".json.gz"):
            p = cong_dir / f"{stem}{ext}"
            if p.exists():
                p.unlink()
                deleted.append(p)
    if deleted:
        print(f"records-output=none: deleted {len(deleted)} per-record file(s):")
        for p in deleted:
            print(f"  {p}")


def _read_tail(path: Path, n_lines: int) -> str:
    try:
        with open(path, "r") as f:
            lines = f.readlines()
    except OSError:
        return ""
    return "".join(lines[-n_lines:])


def _records_ext(records_output: str) -> str:
    """Per-record file extension actually written to disk.

    'none' still writes gz under the hood; the orchestrator deletes them
    after the matrix stage exits ok (see §4 of the sprint plan).
    """
    return ".json" if records_output == "json" else ".json.gz"


def _stage_outputs(
    stage: str, run_dir: Path, records_ext: str, run_id: str,
) -> list[Path]:
    if stage == "ercot":
        return [run_dir / "congestion" / f"ercot_results{records_ext}"]
    if stage == "matrix":
        return [run_dir / "matrix" / "congestion_matrices.npz"]
    if stage == "correlation_map":
        return [run_dir / "mapping" / f"mapping_correlation_{run_id}.npz"]
    if stage == "basis_regression":
        return [run_dir / "mapping" / f"mapping_basis_{run_id}.npz"]
    if stage == "cca":
        return [run_dir / "mapping" / f"mapping_cca_{run_id}.json"]
    if stage == "clustering":
        return [run_dir / "clustering" / "summary.json"]
    if stage == "scorecard":
        return [run_dir / "mapping" / f"scorecard_{run_id}.json"]
    raise ValueError(stage)


def _stage_cmd(
    stage: str,
    args: argparse.Namespace,
    records_subflag: str,
) -> list[str]:
    """Build the subprocess command for a stage.

    `records_subflag` is 'gz' or 'json' (the orchestrator translates
    'none' -> 'gz' before calling).
    """
    base = [sys.executable, "-m"]
    if stage == "ercot":
        return base + [
            "compute.congestion.ercot_runner",
            "--run-id", args.run_id,
            "--dates-file", str(args.dates_file),
            "--records-output", records_subflag,
        ]
    if stage == "matrix":
        cmd = base + [
            "compute.matrix",
            "--run-id", args.run_id,
            "--dates-file", str(args.dates_file),
        ]
        refs = _list_arg(args.ref_methods)
        if refs:
            cmd += ["--ref-methods", *refs]
        return cmd
    if stage == "correlation_map":
        return base + [
            "compute.mapping.correlation_map",
            "--run-id", args.run_id,
        ]
    if stage == "basis_regression":
        return base + [
            "compute.mapping.basis_regression",
            "--run-id", args.run_id,
        ]
    if stage == "cca":
        return base + [
            "compute.mapping.cca",
            "--run-id", args.run_id,
        ]
    if stage == "clustering":
        cmd = base + [
            "compute.clustering.runner",
            "--run-id", args.run_id,
            "--coords-model", str(args.coords_model),
        ]
        # --ref-methods is not forwarded — CM.6 fixed the clustering ref axis
        # on the default (system_lambda_merit_order). Matrix still consumes it.
        if args.algos:
            cmd += ["--algos", args.algos]
        if args.ks:
            cmd += ["--ks", args.ks]
        return cmd
    if stage == "scorecard":
        return base + [
            "compute.mapping.scorecard",
            "--run-id", args.run_id,
            "--algo", args.scorecard_algo,
            "--k", str(args.scorecard_k),
        ]
    raise ValueError(stage)


def _run_stage(
    stage: str,
    cmd: list[str],
    outputs: list[Path],
    run_dir: Path,
    meta: dict,
    meta_path: Path,
    skip_completed: bool,
    force: bool,
) -> bool:
    """Execute one stage; return True on ok/skipped, False on failure."""
    if not force and skip_completed and all(p.exists() for p in outputs):
        meta["stages"][stage] = {"status": "skipped", "elapsed_s": 0.0}
        _write_meta(meta_path, meta)
        print(f"skip: {stage} already complete")
        return True

    log_path = run_dir / f"{stage}.log"
    print(f"\n=== stage: {stage} ===")
    print(f"  cmd: {' '.join(cmd)}")
    print(f"  log: {log_path}")

    started = time.monotonic()
    with open(log_path, "w") as logf:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            logf.write(line)
            logf.flush()
        proc.wait()
    elapsed = round(time.monotonic() - started, 2)

    if proc.returncode != 0:
        meta["stages"][stage] = {
            "status": "failed",
            "elapsed_s": elapsed,
            "returncode": proc.returncode,
            "traceback": _read_tail(log_path, TAIL_LINES),
        }
        _write_meta(meta_path, meta)
        print(
            f"\nFAILED: {stage} exited {proc.returncode} after {elapsed}s "
            f"(see {log_path})",
            file=sys.stderr,
        )
        return False

    meta["stages"][stage] = {"status": "ok", "elapsed_s": elapsed}
    _write_meta(meta_path, meta)
    print(f"ok: {stage} ({elapsed}s)")
    return True


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
                    help="Comma list passed to clustering --algos. Default: all four.")
    ap.add_argument("--ks", default=None,
                    help="Comma list of ints passed to clustering --ks. Default: 4,6,8,10,12,16.")
    ap.add_argument("--scorecard-algo", default="hierarchical_on_beta",
                    help="Clustering algo the scorecard aggregates over "
                         "(must be in --algos; default hierarchical_on_beta).")
    ap.add_argument("--scorecard-k", type=int, default=6,
                    help="Cluster count the scorecard aggregates over "
                         "(must be in --ks; default 6).")
    ap.add_argument("--records-output", choices=("gz", "json", "none"), default="gz",
                    help="Per-record output format for congestion stages. "
                         "'none' keeps gz on disk but deletes them after matrix "
                         "exits ok (default: gz).")
    ap.add_argument("--coords-model", type=Path, default=DEFAULT_COORDS_MODEL,
                    help=f"Bus coords CSV for clustering. Default: {DEFAULT_COORDS_MODEL}.")
    ap.add_argument("--coords-ercot", type=Path, default=DEFAULT_COORDS_ERCOT,
                    help=f"ERCOT settlement-point coords CSV. Default: {DEFAULT_COORDS_ERCOT}.")
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

    records_ext = _records_ext(args.records_output)
    records_subflag = "json" if args.records_output == "json" else "gz"

    for stage in STAGES:
        cmd = _stage_cmd(stage, args, records_subflag)
        outputs = _stage_outputs(stage, run_dir, records_ext, args.run_id)
        ok = _run_stage(
            stage, cmd, outputs, run_dir, meta, meta_path,
            skip_completed=args.skip_completed, force=args.force,
        )
        if not ok:
            return 4
        if stage == "matrix" and args.records_output == "none":
            _drop_per_record(run_dir)

    print(f"\nrun_dir: {run_dir}")
    print(f"size:    {_dir_size_human(run_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
