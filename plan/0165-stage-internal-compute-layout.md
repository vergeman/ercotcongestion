# 0165 - Stage-internal compute layout

Type: refactor
Branch: refactor/0165-stage-internal-compute-layout

## Goal

* Organize `sf_map` and `mu_forecast` by their processing responsibilities rather than flat module names.
* Keep raw reusable data access in `inputs`, model-facing covariates in `mu_forecast`, and all production behavior unchanged.
* Migrate every production, experiment, probe, and test import atomically without compatibility stubs.

## Context

* Plan 0164 established the top-level production stages, but `sf_map` and especially `mu_forecast/mu_model.py` still combine multiple layers at their package roots.
* An implied-SF map is both a time-versioned operational matrix for nodal projection and an input to derived constraint geography; those are separate downstream responsibilities.
* Weather, outage exposure, and geography are model-specific feature transformations, not generic source readers, because they apply causal/vintage and feature-engineering rules.

## Approach

* Work in: `compute/sf_map/`, `compute/mu_forecast/`, and all affected callers/tests/docs.
* Entry point / primary change: retain `compute.jobs.weekly_map` and `compute.jobs.daily_forecast` as production CLIs while giving each stage an internal pipeline layout.
* Move SF fitting primitives to `sf_map/model/{fit,grouping,rolling,diagnostics}.py`; move persisted-map read/write operations to `sf_map/storage/{maps,persist}.py`; and move inferred constraint geography derivation/materialization to `sf_map/geography/{derive,persist}.py`.
* Preserve `sf_map/config.py` as the single source of the adopted operating point; replace leaf imports in projection, evaluation, jobs, experiments, probes, and tests with their canonical new locations.
* Move μ causal cutoffs, source readers, feature engineering, and panel assembly to `mu_forecast/panel/{availability,sources,engineering,build}.py`; make `build.py` the narrow panel-construction API.
* Group optional model predictor families beneath `mu_forecast/covariates/`: weather and `outages/{crosswalk,exposure}`; remove the `mu_forecast.geo` re-export and import SF geography directly where required.
* Split `mu_model.py` into model configuration/feature-arm selection, head primitives, scheduling, backtest execution, daily prediction, and prediction-artifact persistence; retain only intentional public APIs at canonical module paths and migrate every caller in the same commit group.
* Move neutral delivery-day/time helpers out of reverse `sf_map → mu_forecast` imports where possible, without changing CT/DST or DAM-close semantics.
* Update the compute architecture documentation and model tutorial outline with the internal processing flow and canonical import paths.
* Do NOT change SQL, data-vintage cutoffs, feature values/order, model parameters, refit grids, RNG ordering, NPZ bytes, database schemas, artifact directories, forecast pointer/write order, production CLI arguments, experiment behavior, or probe outputs.

## Commit groups

* **1 — SF-map internals:** relocate fit/model, map storage, and geography modules; migrate weekly-map, projection, evaluation, experiment, probe, and SF-test imports; remove old files in the same commit.
* **2 — μ panel and covariates:** establish panel and covariate packages, move availability/source/engineering/weather/outage code, eliminate the geographic re-export, and migrate all feature callers/tests atomically.
* **3 — μ model execution:** split the model runner into configuration, backtest, daily prediction, and artifact concerns; migrate daily/backfill jobs, experiments, and model tests; remove `mu_model.py`.
* **4 — Boundaries and documentation:** remove remaining stale imports, add/adjust import-boundary coverage, update architecture/tutorial documentation, and run the focused regression suite.

## Acceptance

* [x] `sf_map` has separate model, storage, and geography packages, while the weekly-map and projection results remain identical for fixed inputs.
* [ ] `mu_forecast` has panel, covariate, and model-execution packages; `mu_model.py` and `geo.py` no longer exist, and no compatibility import stubs remain.
* [ ] Raw source access remains in `compute.inputs` or `mu_forecast.panel.sources`; model-specific weather, outage, and geographic transformations reside under `mu_forecast.covariates`.
* [ ] Every production job, evaluation, experiment, probe, tutorial, and test uses canonical paths; no tracked source/docs refer to moved module paths.
* [ ] Focused SF and μ test suites pass, with fixed-input SF, panel, μ prediction, and fixed-seed projection regression outputs unchanged.
