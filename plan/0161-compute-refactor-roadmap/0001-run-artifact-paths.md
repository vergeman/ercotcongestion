# 0161-0001 - Centralize run-artifact paths

Type: refactor
Branch: refactor/0161-compute-refactor-roadmap/0001-run-artifact-paths

## Goal

* Define one dependency-light catalog for run-scoped artifact locations.
* Preserve all existing path strings and explicit CLI overrides.

## Context

* `mu_model`, `daily_forecast`, and `backfill_nodal` each derive `runs/<run-id>/mu/mu_preds.npz`.
* The duplicated helpers currently avoid a circular import rather than express a shared ownership boundary.

## Approach

* Work in: `compute/artifacts.py`, `compute/mu/mu_model.py`, `compute/jobs/daily_forecast.py`, `compute/jobs/backfill_nodal.py`.
* Introduce a `RunArtifacts` value object or pure functions for the canonical `mu/` and `forecast/` paths; accept a root for testability.
* Migrate callers to the catalog while retaining existing public `*_path_for` wrappers as delegations during this change.
* Keep run-id-less legacy fallback behavior in `resolve_walk_paths` unchanged.
* Do NOT touch artifact formats, CLI flag precedence, or filesystem write timing.

## Acceptance

* [x] The three callers resolve byte-identical paths for representative run IDs.
* [x] Existing path-resolution tests pass, including `RUNS_ROOT` test overrides.
* [x] No imports create a `daily_forecast` ↔ `backfill_nodal` cycle.

## Suggested regression tests

* Parametrize run IDs and roots, then assert `RunArtifacts` and every retained `*_path_for` wrapper produce the same `Path` for weekly metrics, predictions, scores, bands, and nodal panels.
* Exercise `resolve_walk_paths` for run-id, explicit override, run-id-less legacy, and `--load-nodal-npz` modes; assert the exact prior paths win in each case.
