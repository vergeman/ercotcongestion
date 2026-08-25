# 0166 - Direct module imports

Type: refactor
Branch: refactor/0166-direct-module-imports

## Goal

* Import internal helpers from their implementation modules instead of one-line compatibility re-exports.
* Preserve runtime behavior, public import compatibility, and existing test patch points.
* Add a focused import-boundary check so new indirect internal imports do not return.

## Context

* `compute.mu_forecast.panel.build` re-exports availability, engineering, and source helpers; current consumers include daily forecasting, grading, runner/covariate code, and tests.
* `compute.projection.propagate` re-exports codecs, sampling, and map-storage helpers to jobs, analysis, experiments, and tests.
* `compute.config` documents itself as a legacy settings facade, but eight compute modules still import its `PG_DSN` alias.
* Compatibility exports may be needed by external callers and tests; this refactor changes internal consumers first and does not alter time/DST semantics.

## Approach

* Work in: `compute/`, especially `mu_forecast/panel/`, `projection/`, `jobs/`, `analysis/`, `experiments/`, and their tests.
* Entry point / primary change: replace imports whose imported symbol is a direct alias of another module's implementation.
* Build a small, reviewed inventory of direct aliases and their consumers (including multiline imports); distinguish true façade aliases from functions implemented by the imported module and from intentional package-level APIs.
* Migrate panel consumers to `availability`, `engineering`, `sources`, or `compute.time` as appropriate; in particular, replace `ERCOT_TZ`, CT-boundary, DAM-close, history-cutoff, calendar, and source-panel imports that currently pass through `panel.build`.
* Migrate projection consumers to `projection.codecs`, `projection.sampling`, and `sf_map.storage.maps` when they import aliases rather than `propagate_window` or other projection logic implemented in `propagate.py`.
* Replace legacy `compute.config.PG_DSN` imports with `shared.settings.settings.pg_dsn`, preserving each command's existing DSN behavior.
* Keep compatibility assignments in their current modules and retain local semantic wrappers such as job-level CT-day names when callers or tests use them; do not move implementations or change public paths in this pass.
* Add or extend a narrow static regression test/check covering the reviewed alias inventory and run the affected panel, projection, forecast, and settings-consumer tests.
* Do NOT touch: helper algorithms, timestamp storage/CT delivery-date behavior, SQL, CLI arguments, artifact formats, or compatibility-export removal.

## Acceptance

* [x] Internal production consumers no longer import reviewed one-line aliases through `panel.build`, `projection.propagate`, or `compute.config`; imports resolve to the owning module.
* [x] `panel.build` and `projection.propagate` imports remain only for implementations those modules actually own (for example `build_panel` and `propagate_window`) or an explicitly documented compatibility exception.
* [x] Existing compatibility import paths continue to resolve, and targeted DST/time, panel, projection, daily-forecast, grading, and settings-consumer tests pass.
* [x] The import-boundary check fails when a newly reviewed indirect alias is imported through an intermediary module.
