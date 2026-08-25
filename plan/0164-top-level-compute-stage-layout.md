# 0164 - Top-level compute stage layout

Type: refactor
Branch: refactor/0164-top-level-compute-stage-layout

## Goal

* Reorganize production compute libraries around inputs, SF-map fitting, μ forecasting, projection, and evaluation stages.
* Make production jobs depend on stage-level public APIs instead of `compute.sf.*` and `compute.mu.*` leaf modules.
* Preserve all forecast/map calculations, database schemas, artifact bytes, and scheduled-job behavior while removing obsolete package paths.

## Context

* Plan 0162 separated production code from `experiments/` and `probes/`; plan 0161 extracted the seams needed to move stage responsibilities safely.
* `compute/sf/project.py` and `compute/sf/codecs.py` are cross-model projection/artifact code, while `sf/eval.py`, `sf/essp.py`, and `mu/score.py` are evaluation code.
* API, analysis, jobs, tests, and experiments now import the stage packages; the short-lived compatibility façades are no longer needed.

## Approach

* Work in: `compute/`, `api/`, `plan/`, and affected tests/docs.
* Entry point / primary change: create stage packages: `compute/inputs/`, `compute/sf_map/`, `compute/mu_forecast/`, `compute/projection/`, and `compute/evaluation/`.
* Establish an import-direction rule and enforce it with an import-graph test: `inputs → {sf_map, mu_forecast} → projection → evaluation`; `jobs/`, `analysis/`, and `api/` consume stage APIs only. `experiments/` and `probes/` remain leaf clients of those APIs.
* Move `sf.panels` into `inputs/dam.py`; keep `compute.sf.panels` as a re-export until all callers migrate. Keep DAM coverage/reference semantics and SQL unchanged.
* Move SF fitting, rolling, diagnostics, grouping, map persistence/store, and map geography into `sf_map/`; expose a deliberately small façade for the weekly map job and causal map loading.
* Move μ availability, source readers, panel engineering, feature assembly, two heads, scheduling, prediction artifacts, and optional `geo`/`weather`/`outage` arms into `mu_forecast/`; retain `build_panel`, `predict_day`, and feature-set behavior unchanged.
* Move nodal codecs, residual sampling, SF+μ artifacts, and `propagate_window` into `projection/`; remove the projection layer's dependency on `mu.score` by sourcing shared operating defaults and pure metrics from their owning stage/common module.
* Move μ scoring, SF OOS evaluation, ESSP validation, and shared scoring metrics into `evaluation/`; preserve CLI compatibility for `compute.sf.eval` and the current score entry point through thin forwarding modules.
* Update `compute.jobs.*`, `compute.analysis.*`, `api/*`, tests, docs, and deploy manifests to use only stage-level imports/CLI paths; remove the old `compute/sf/` and `compute/mu/` packages.
* Update `compute/README.md` and `compute/experiments/model_tutorial/PRODUCTION_OUTLINE.md` to describe the canonical stage packages and compatibility period.
* Do NOT change model parameters, training/refit grids, query/vintage cutoffs, RNG ordering, NPZ serialization format, database tables, artifact schemas, forecast pointer/write ordering, experiment results, or probe behavior.

## Commit groups

* **1 — Contracts and inputs:** add stage-package skeletons, centralize dependency-light shared constants/metric ownership, move DAM readers to `inputs`, and add import-boundary tests with legacy re-exports intact.
* **2 — SF map and μ forecast:** relocate their model-specific internals behind `sf_map` and `mu_forecast` façades; migrate jobs and focused tests without changing outputs.
* **3 — Projection and evaluation:** relocate shared nodal projection/artifacts and evaluators; migrate API, analysis, backfill, and grade consumers; retain byte-for-byte/fixed-seed regression fixtures.
* **4 — Canonicalize and document:** migrate experiments, tests, docs, and deployment commands to stage APIs; remove legacy façades; and run the focused suite.

## Acceptance

* [x] Canonical production libraries exist at `compute.inputs`, `compute.sf_map`, `compute.mu_forecast`, `compute.projection`, and `compute.evaluation`, with documented dependency direction and no forbidden reverse imports.
* [x] `weekly_map`, `daily_forecast`, `backfill_nodal`, `backfill_artifacts`, `grade_day`, API/analysis consumers, and their tests import stage façades rather than legacy `compute.sf.*` / `compute.mu.*` leaves.
* [x] Legacy façade files are removed; no tracked source, tests, docs, or deploy manifests refer to `compute.sf.*` or `compute.mu.*`.
* [x] Fixed-input SF matrices, fixed-seed projection draws/percentiles/artifact bytes, feature-panel frames, μ predictions, and map-store failure guards match pre-refactor fixtures exactly.
* [x] Focused SF and μ suites pass (`325 passed, 1 skipped`); no scheduled command, DB write contract, or artifact schema changes.
