"""compute.promote — one command to flip a run to "live".

Two selection planes serve the frontend today:

* Filesystem-served state (scorecard JSON/NPZ, cluster labels) sits on
  the shared runs volume. Which run/cell is served is decided by
  symlinks — no envs, no query params.
* DB-served state (implied binding proximity rows) is selected by the
  ``implied_binding_proximity_current[layer]`` pointer.

Historically these were flipped separately (env-var change + rollout,
``implied_binding_proximity.ingest --promote``). This CLI collapses both
into a single op.

For the IBP layer it does the *whole* job: it backfills the run's
``bp_ercot.npz`` into ``implied_binding_proximity`` (the npz is
authoritative — rows are re-synced from it) and flips the served pointer
in one transaction. So a fresh run can be served end-to-end with just
``--promote`` — no separate ``ingest``/``--ibp-persist`` step. When the npz
is gone but rows are already persisted, it falls back to a bare pointer
flip.

Usage (inside the ``compute`` docker service; needs psycopg + db)::

    python -m compute.promote \
        --run-id v1-annual \
        --ref kkt_perbus \
        --algo hierarchical_on_beta \
        --k 6

Ordering: the IBP DB step (persist rows + flip pointer) runs first — it is
the most failure-prone (DB, the system_lambda ref guard, a missing npz), so
a failure there leaves the filesystem untouched. Then cell-level symlinks
inside the run dir, then the top-level ``current`` link. Re-running
converges: symlinks are idempotent, and the IBP rows are re-synced from the
(unchanged) npz.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from compute.implied_binding_proximity.ingest import ingest_run
from compute.implied_binding_proximity.persist import (
    DEFAULT_LAYER,
    promote_layer,
)

log = logging.getLogger("compute.promote")


def _cell_targets(run_id: str, ref: str, algo: str, k: int) -> list[tuple[str, str]]:
    """Return ``(symlink_name, target_filename)`` pairs for the cell flips.

    All targets are basenames living in the same directory as the symlink,
    so ``readlink`` returns a clean per-cell filename.
    """
    return [
        ("mapping/scorecard.json",
         f"scorecard_{run_id}_{ref}_{algo}_k{k}.json"),
        ("mapping/scorecard_series.npz",
         f"scorecard_series_{run_id}_{ref}_{algo}_k{k}.npz"),
        ("clustering/cluster_labels.npz",
         f"cluster_labels_{ref}_{algo}_k{k}.npz"),
        # Run-scoped, not cell-scoped (no ref/algo/k) — depends only on
        # run_id, but flipped here alongside the cell links since promote
        # only walks this one list.
        ("mapping/mapping_correlation_summary.json",
         f"mapping_correlation_summary_{run_id}.json"),
    ]


def _needs_flip(link_path: Path, target_name: str) -> bool:
    """True if ``link_path`` doesn't already resolve to ``target_name``.

    Uses ``readlink`` on the link itself so a repointed symlink counts as
    a change even if the eventual file is identical.
    """
    try:
        return os.readlink(link_path) != target_name
    except (FileNotFoundError, OSError):
        return True


def _atomic_symlink(link_path: Path, target_name: str) -> None:
    """``ln -sfn target_name link_path`` — atomic rename semantics."""
    tmp = link_path.with_suffix(link_path.suffix + f".{os.getpid()}.tmp")
    if tmp.exists() or tmp.is_symlink():
        tmp.unlink()
    os.symlink(target_name, tmp)
    os.replace(tmp, link_path)


def promote(
    run_id: str,
    ref: str,
    algo: str,
    k: int,
    runs_root: Path,
    layer: str = DEFAULT_LAYER,
    dry_run: bool = False,
) -> int:
    """Execute the promote steps. Returns process exit code."""
    run_dir = runs_root / run_id
    if not run_dir.is_dir():
        log.error("run dir does not exist: %s", run_dir)
        return 2

    cell_targets = _cell_targets(run_id, ref, algo, k)
    missing = [
        run_dir / rel_target(link_rel, tgt)
        for link_rel, tgt in cell_targets
        if not (run_dir / rel_target(link_rel, tgt)).exists()
    ]
    if missing:
        for path in missing:
            log.error("target file missing: %s", path)
        log.error(
            "refusing to promote — build the cell first with "
            "compute.mapping.scorecard / compute.clustering.runner"
        )
        return 2

    # IBP DB first — before any symlink flips. This step is the riskiest part
    # of a promote (DB availability, the system_lambda ref guard, a missing
    # npz), so doing it first means a failure here leaves the filesystem
    # untouched rather than half-flipped. The run's bp_ercot.npz is
    # authoritative: re-sync the served rows from it, then flip the pointer in
    # the same transaction. This is what lets `--promote` (here and via
    # run_pipeline) serve a fresh run end-to-end without a separate persist
    # step. Falls back to a bare pointer flip when the npz is gone but rows are
    # already persisted.
    if dry_run:
        log.info(
            "DRY-RUN would persist ibp rows + promote layer=%s -> run_id=%s",
            layer, run_id,
        )
        step3_writes = 1
    else:
        npz_path = run_dir / "ibp" / "bp_ercot.npz"
        if npz_path.exists():
            try:
                n_rows = ingest_run(
                    run_id, runs_root=runs_root, promote=True, layer=layer,
                )
            except ValueError as e:  # non-distributed-slack ref
                log.error("%s", e)
                return 2
            log.info(
                "persisted %d ibp rows + promoted DB layer=%s -> run_id=%s",
                n_rows, layer, run_id,
            )
            step3_writes = 1
        else:
            # No artifact to backfill from — flip the pointer only if rows are
            # already persisted (promote_layer raises otherwise).
            try:
                step3_writes = 1 if promote_layer(run_id, layer=layer) else 0
            except ValueError as e:
                log.error("%s", e)
                return 2
            if step3_writes:
                log.info(
                    "promoted DB layer=%s -> run_id=%s (npz absent; used "
                    "existing rows)", layer, run_id,
                )
            else:
                log.info("no change: DB layer=%s already at run_id=%s", layer, run_id)

    # Step 1: per-cell symlinks inside the run dir.
    step1_writes = 0
    for link_rel, target_name in cell_targets:
        link_path = run_dir / link_rel
        if _needs_flip(link_path, target_name):
            if dry_run:
                log.info("DRY-RUN would flip %s -> %s", link_path, target_name)
            else:
                link_path.parent.mkdir(parents=True, exist_ok=True)
                _atomic_symlink(link_path, target_name)
                log.info("flipped %s -> %s", link_path, target_name)
            step1_writes += 1
        else:
            log.info("no change: %s -> %s", link_path, target_name)

    # Step 2: top-level current -> <run_id>.
    top_link = runs_root / "current"
    if _needs_flip(top_link, run_id):
        if dry_run:
            log.info("DRY-RUN would flip %s -> %s", top_link, run_id)
        else:
            _atomic_symlink(top_link, run_id)
            log.info("flipped %s -> %s", top_link, run_id)
        step2_writes = 1
    else:
        log.info("no change: %s -> %s", top_link, run_id)
        step2_writes = 0

    total = step1_writes + step2_writes + step3_writes
    if total == 0:
        log.info("no changes — everything already at run_id=%s cell=%s/%s/k%d",
                 run_id, ref, algo, k)
    return 0


def rel_target(link_rel: str, target_name: str) -> str:
    """Path (relative to the run dir) of the target file the symlink points at.

    ``target_name`` is a basename living in the same directory as the
    symlink, so the resolved path is ``dirname(link_rel)/target_name``.
    """
    return f"{os.path.dirname(link_rel)}/{target_name}"


def _build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Flip a run to serving (symlinks + IBP DB pointer).",
    )
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--ref", required=True,
                    help="Reference method (e.g. kkt_perbus).")
    ap.add_argument("--algo", required=True,
                    help="Clustering algorithm (e.g. hierarchical_on_beta).")
    ap.add_argument("--k", type=int, required=True)
    ap.add_argument("--layer", default=DEFAULT_LAYER,
                    help=f"IBP DB layer to flip (default {DEFAULT_LAYER}).")
    ap.add_argument("--runs-root", type=Path,
                    default=Path(os.environ.get("COMPUTE_RUNS_DIR", "/compute/runs")),
                    help="Root directory holding <run_id> subdirs and 'current'.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report what would change; touch nothing.")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    return promote(
        run_id=args.run_id,
        ref=args.ref,
        algo=args.algo,
        k=args.k,
        runs_root=args.runs_root,
        layer=args.layer,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
