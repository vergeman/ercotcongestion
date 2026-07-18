# 0097 - compute-pipeline-remove-ibp

Type: refactor
Branch: refactor/0097-compute-pipeline

## Goal

* Purge the retired binding-proximity (`bp`/`ibp`) vocabulary from active compute code and docs.
* Everything that names the shift-factor pipeline refers to SF, not binding proximity.

## Context

* `bp` ("binding proximity") is a retired metric; the pipeline it labeled now fits shift factors (SF).
* `rolling_bp` was already stripped to a pure SF window-walker (plan 0093) but kept its name.
* Historical records (`plan/`, `docs/legacy/`) are out of scope — their `bp` refs are accurate to their era.

## Approach

* Work in: `compute/` (+ `db/migrations/25_implied_shift_factors.sql` comment).
* `compute/jobs/weekly_map.py`: output subdir `runs/<run_id>/ibp/` → `sf/`; docstring/flag comments de-bp'd.
* `compute/sf/rolling.py`: rename `rolling_bp` → `rolling_sf`; update all callers (`weekly_map`, `persist.py`, `tests/test_grouped_fit.py`) and docstring refs (`eval.py`, `experiments/.../common.py`).
* `compute/sf/__init__.py`, `diagnostics.py`, `README.md`, `r3_verdict.py`: rewrite bp-era docstrings/paths (stale `bp_ercot.*`, `ibp/` diagnostics path, example sweep CSV, `bp = max|SF|` aside).
* `compute/mu/score.py`: fix `experiments/ibp_out_of_window` path refs; `mu/ablate.py`: rename local `bp` → `bands_path`.
* `git mv compute/experiments/ibp_out_of_window` → `sf_out_of_window`; fix `python -m` module paths + README title inside.
* `compute/runs/README.md`: `ibp/` artifact block → `sf/` (drop retired `bp_ercot.npz`); `ibp_sweep_*` run-id convention → `sf_sweep_*`.
* Do NOT touch: `plan/**`, `docs/legacy/**`; historical/narrative `bp` prose in the moved experiment README.

## Acceptance

* [x] `grep -rn "rolling_bp" compute --include=*.py` returns nothing (outside `__pycache__`).
* [x] No `ibp`/`bp` identifier or path in active compute code (excl. `runs/` data, `legacy/`, frozen experiment narrative).
* [x] `experiments/sf_out_of_window` runs under its new module path; no stale `ibp_out_of_window` import.
* [x] `pytest /compute/sf/tests` passes (46 passed).
