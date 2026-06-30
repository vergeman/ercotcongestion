# 0022 - lift-to-compute

Type: refactor
Branch: refactor/lift-to-compute

## Goal

* Lift production-grade modules from `compute/experiments/{congestion_calculation,zonal_clustering}/` into first-class packages under `compute/`.
* Relocate sample-specs (`compute/profiling/`) to `compute/sample_specs/` and delete the dead profiling snapshot runner.
* Drop every `sys.path.insert(0, '/compute')` hack; rewrite imports as package-style. No behavior change.

## Context

* `congestion_calculation/` and `zonal_clustering/` are no longer experiments — they're the pipeline. Keeping them under `experiments/` masks that and forces `sys.path` hacks at the top of every script.
* `compute/profiling/reference_snapshot.py` and `reference_snapshots.json` are dead (superseded by `compute/test_snapshot.py`); the dates spec and extractor still need a first-class home.
* 0021 already established `compute/runs/legacy-test-persist/` — the per-commit smoke target.

## Approach

* Work in: `compute/`, `compute/experiments/`. Use `git mv` so rename detection preserves blame.
* Three commits, each independently re-runnable against the 11-snapshot replay:

**2a — lift congestion**
* Add `compute/__init__.py`, `compute/congestion/__init__.py`.
* `git mv experiments/congestion_calculation/congestion.py compute/congestion/compute.py`
* `git mv experiments/congestion_calculation/system_lambda_estimators.py compute/congestion/system_lambda_estimators.py`
* `git mv experiments/congestion_calculation/congestion_snapshot.py compute/congestion/snapshot_runner.py`
* `git mv experiments/congestion_calculation/ercot_congestion_snapshot.py compute/congestion/ercot_runner.py`
* `git mv experiments/congestion_calculation/congestion_matrix.py compute/matrix.py`
* Delete the now-empty `experiments/congestion_calculation/`.
* Drop `sys.path.insert(...)` hacks; rewrite to package-style imports (`from compute.snapshot import ...`, `from .compute import compute_congestion` within the package).
* Update plan docs / READMEs that reference the old paths.
* Smoke: `python -m compute.congestion.snapshot_runner --dates-file …` → `python -m compute.matrix --model-results …` reproduces `compute/runs/legacy-test-persist/` outputs byte-for-byte (modulo JSON key ordering).

**2b — lift clustering**
* Add `compute/clustering/__init__.py`.
* `git mv experiments/zonal_clustering/{clustering.py,diagnostics.py,polygons.py,select_zones.py,run_clustering.py,tests}` → `compute/clustering/{algorithm.py,diagnostics.py,polygons.py,select_zones.py,runner.py,tests}`.
* Delete `experiments/zonal_clustering/`.
* Rewrite imports: `from experiments.zonal_clustering.clustering import ...` → `from compute.clustering.algorithm import ...` (or relative `from .algorithm import ...`).
* Smoke: clustering sweep on 2a's matrix output reproduces the legacy clustering artifacts.

**2c — relocate sample specs**
* Delete `compute/profiling/reference_snapshot.py` and `compute/profiling/reference_snapshots.json` (dead).
* Add `compute/sample_specs/__init__.py`.
* `git mv compute/profiling/extract_sample_snapshot_dates.py compute/sample_specs/extract_dates.py`
* `git mv compute/profiling/reference_dates.json compute/sample_specs/reference_dates.json`
* Remove the empty `compute/profiling/` directory.
* Update the 7 active references to `compute/profiling/reference_dates.json`:
  - `compute/congestion/snapshot_runner.py`, `compute/congestion/ercot_runner.py` (`DEFAULT_DATES_FILE`).
  - `compute/experiments/zonal_load/{compare_zonal_lmp,cap_sweep,line_expansion_candidates/far_west_candidates,permian_backbone/pilot_backbone,feasibility_diagnosis/diagnose_zonal_infeasibility}.py` (`REF_DATES` constant).
* Smoke: `grep -rn "profiling" compute/` returns zero hits; 11-snapshot replay still reproduces.

* Do NOT touch: `compute/write_snapshots.py`, `compute/test_snapshot.py`, `compute/snapshot.py`, or any other top-level `compute/*.py`. Do NOT add new behavior — mechanical moves + import rewrites only.

## Acceptance

* [ ] `compute/__init__.py`, `compute/congestion/__init__.py`, `compute/clustering/__init__.py`, `compute/sample_specs/__init__.py` exist.
* [ ] `compute/experiments/congestion_calculation/`, `compute/experiments/zonal_clustering/`, `compute/profiling/` are deleted.
* [ ] No `sys.path.insert` calls remain in any lifted file (`grep -rn 'sys.path.insert' compute/` returns 0 hits inside lifted files).
* [ ] `grep -rn 'profiling' compute/` returns 0 hits.
* [ ] After each commit (2a, 2b, 2c), the 11-snapshot replay reproduces the matching `compute/runs/legacy-test-persist/` artifact.
* [ ] `git log --follow` on each moved file shows the pre-lift history (rename detection preserved blame).
* [ ] `compute/clustering/tests/` passes: `pytest compute/clustering/tests/`.
