"""compute.promote — one command to flip a run to "live".

The zonal/clustering frontend is filesystem-served: the scorecard JSON/NPZ
and cluster labels sit on the shared runs volume, and which run/cell is
served is decided by symlinks — no envs, no query params. This CLI flips
those symlinks atomically.

Usage (inside the ``compute`` docker service)::

    python -m compute.promote \
        --run-id v1-annual \
        --ref kkt_perbus \
        --algo hierarchical_on_beta \
        --k 6

Ordering: cell-level symlinks inside the run dir first, then the top-level
``current`` link. Re-running converges — symlinks are idempotent.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

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

    total = step1_writes + step2_writes
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
        description="Flip a run to serving (symlinks).",
    )
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--ref", required=True,
                    help="Reference method (e.g. kkt_perbus).")
    ap.add_argument("--algo", required=True,
                    help="Clustering algorithm (e.g. hierarchical_on_beta).")
    ap.add_argument("--k", type=int, required=True)
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
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
