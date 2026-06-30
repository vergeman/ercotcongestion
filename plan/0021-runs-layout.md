# 0021 - runs-layout

Type: chore
Branch: chore/runs-layout

## Goal

* Establish `compute/runs/<run_id>/` as the canonical artifact tree without touching compute logic.
* Migrate the loose untracked artifacts from `compute/experiments/congestion_calculation/` and `compute/experiments/zonal_clustering/runs/test-persist/` into the new tree under `legacy-*` run_ids.
* Add `compute/runs/` to `.gitignore` and document the per-run subdir layout.

## Context

* Phase 3 stages (congestion, matrix, clustering) currently land outputs loose in source directories with ad-hoc names. Only `zonal_clustering` has a `runs/<name>/` convention; nothing upstream does.
* At 11 snapshots congestion JSON is ~6.4 MB; at 120 it is ~70 MB. Multiple ref-method runs at scale would litter source directories with hundreds of MB.
* Phase 4 (validation framework) will consume matched (congestion, matrix, clusters) triples from a known input window — easier on top of a `runs/<run_id>/` contract.

## Approach

* Work in: `compute/runs/` (new), `compute/experiments/congestion_calculation/`, `compute/experiments/zonal_clustering/runs/`.
* Add `compute/runs/` to `.gitignore`.
* Move the five untracked artifacts in `compute/experiments/congestion_calculation/` into:
  - `compute/runs/legacy-test-persist/congestion/model_results.json` (was `congestion_results_test-persist.json` — confirm name)
  - `compute/runs/legacy-test-persist/matrix/congestion_matrices.npz` (was `congestion_matrices_test-persist.npz`)
  - `compute/runs/legacy-test-persist/matrix/matrix_summary.json` (was `congestion_matrix_test-persist.json`)
  - `compute/runs/legacy-final-merit/{congestion,matrix}/...` for the `final-merit` set (or delete if not needed for comparison).
* Migrate `compute/experiments/zonal_clustering/runs/test-persist/` to `compute/runs/legacy-test-persist/clustering/`.
* Add `compute/runs/README.md` — one paragraph + the per-run tree from phase4-working-outline §2.
* Do NOT touch: any stage script, any import, any CLI flag. Stage scripts still resolve via explicit-path flags pointed at the new locations.

## Acceptance

* [ ] `compute/runs/` listed in `.gitignore`.
* [ ] `compute/runs/legacy-test-persist/{congestion,matrix,clustering}/` populated; `compute/experiments/congestion_calculation/` has no loose `.json`/`.npz` artifacts.
* [ ] `compute/experiments/zonal_clustering/runs/test-persist/` no longer exists.
* [ ] `compute/runs/README.md` documents the per-run subdir layout.
* [ ] Stage scripts re-run with explicit-path flags pointed at the new artifact locations still succeed.
