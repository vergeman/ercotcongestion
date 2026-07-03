# S0.1 - k3s-local-runs-volume

Type: chore
Branch: chore/s0.1-k3s-local-runs-volume

## Goal

* Provision a fast local volume in k3s backing `/runs` for the compute pod.
* Sweeps and re-runs write to the local volume with measurably lower wall-clock time.
* Artifacts under `compute/runs/<run_id>/{matrix,clustering,congestion}` persist across pod restarts.

## Context

* Cloud instance is faster than the current setup; matrix/clustering re-runs are I/O-bound.
* No fast local volume exists today, so every re-run pays remote I/O cost.
* `RUNS_ROOT = BASE_DIR.parent / "runs"` must resolve onto the new mount point without code changes if possible.

## Approach

* Work in: `ops/deploy/` (k3s manifests + launcher scripts).
* Entry point / primary change: `compute-runs` PVC + volume mount at `/compute/runs` in compute workloads.
* Step 1 — add PVC manifest `ops/deploy/base/compute/runs-pvc.yml` using `local-path` storage class (same pattern as `postgres-data`).
* Step 2 — mount `compute-runs` at `/compute/runs` in `ops/deploy/jobs/snapshot_job.yml.template`.
* Step 3 — add `ops/deploy/jobs/compute_shell_pod.yml.template` (standalone pod with the PVC mounted) and `ops/deploy/compute_shell.sh` launcher for interactive sweeps.
* Step 4 — verify `RUNS_ROOT` in `compute/clustering/runner.py` and `compute/run_pipeline.py` resolves to `/compute/runs` (no code change needed given container app root is `/compute`).
* Step 5 — run a v1-120 sweep and record wall-clock time vs. baseline.
* Do NOT touch: compute pipeline logic, clustering/congestion algorithms, or run_id schema.

## Acceptance

* [x] `ops/deploy/base/compute/runs-pvc.yml` exists (`compute-runs` PVC, `local-path`, 50Gi, RWO).
* [x] `ops/deploy/jobs/snapshot_job.yml.template` mounts `compute-runs` at `/compute/runs`.
* [x] `ops/deploy/jobs/compute_shell_pod.yml.template` mounts the same PVC and stays alive for `kubectl exec`.
* [x] `ops/deploy/compute_shell.sh` sources `../../.env`, exports `IMAGE_REPO`/`IMAGE_TAG`, applies the template, waits for Ready, and execs into the pod.
* [x] PVC bound: `kubectl -n ercotstress get pvc compute-runs` shows `STATUS=Bound`.
* [x] Artifacts persist across a compute pod restart (delete pod, re-list run_id directory, files still present).
