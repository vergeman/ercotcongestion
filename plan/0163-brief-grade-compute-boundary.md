# 0163 - Brief grade compute boundary

Type: refactor
Branch: refactor/0163-brief-grade-compute-boundary

## Goal

* Remove the daily forecast job's import dependency on `api.analysis`.
* Preserve Brief-grade rows, API responses, and non-fatal post-publish grading behavior.

## Context

* `compute.jobs.materialize_brief_grade` imports private profile/response helpers from `api.analysis`.
* The compute container does not mount the live API source or include `/api` in its Compose `PYTHONPATH`.
* A missing API module fails `daily_forecast` at import time, before its intended non-fatal grade boundary.

## Approach

* Work in: `compute/analysis/`, `compute/jobs/materialize_brief_grade.py`, `api/analysis.py`, and focused tests.
* Extract shared Brief-grade profile queries and neutral serialization from `api.analysis` into `compute.analysis.brief_grade`.
* Make `materialize_brief_grade` consume the compute module directly; retain the existing DB schema and upsert keys.
* Make `api.analysis` consume the same compute module and wrap its neutral result in API response models.
* Keep `daily_forecast`'s post-publish call and failure handling unchanged; remove all `api.*` imports from compute jobs.
* Do NOT change grade formulas, SQL result scope, API schemas, delivery-day semantics, or forecast write ordering.

## Acceptance

* [ ] `compute.jobs.daily_forecast` and `materialize_brief_grade` import without `/api` on `PYTHONPATH`.
* [ ] Fixed DB fixtures yield identical persisted `analysis_grade_daily` rows before and after extraction.
* [ ] API Brief-grade responses preserve their current schema and values on the same fixtures.
* [ ] Daily forecast publication remains successful when Brief-grade materialization raises after publish.
