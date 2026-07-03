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

* Work in: `ops/` (k3s manifests).
* Entry point / primary change: k3s manifest for the compute pod; volume mount definition.
* Step 1 — add a hostPath (or local PVC) definition in the k3s manifest pointing at a fast local disk path.
* Step 2 — mount the volume into the compute pod at the path `RUNS_ROOT` resolves to.
* Step 3 — verify `compute/clustering/runner.py::RUNS_ROOT` and `run_pipeline.py` path constants resolve onto the mount; update path constants only if the mount point must differ.
* Step 4 — run a v1-120 sweep and record wall-clock time vs. baseline.
* Do NOT touch: compute pipeline logic, clustering/congestion algorithms, or run_id schema.

## Acceptance

* [ ] Sweep artifacts land on the local volume at `compute/runs/<run_id>/{matrix,clustering,congestion}`.
* [ ] v1-120 re-run wall-clock is measurably lower than the pre-change baseline (record both numbers).
* [ ] Artifacts persist across a compute pod restart (delete pod, re-list run_id directory, files still present).
* [ ] `RUNS_ROOT` resolves onto the mounted volume (verified via `ls` inside the pod).
