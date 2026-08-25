# 0166 - Direct module imports

Type: refactor
Branch: refactor/0166-direct-module-imports

## Goal

* Import internal helpers from their implementation modules instead of one-line compatibility re-exports.
* Remove panel and projection compatibility facades once every repository consumer imports the owning module.
* Add a focused import-boundary check so new indirect internal imports do not return.

## Context

* `compute.mu_forecast.panel.build` re-exports availability, engineering, and source helpers; current consumers include daily forecasting, grading, runner/covariate code, and tests.
* `compute.projection.propagate` re-exports codecs, sampling, and map-storage helpers to jobs, analysis, experiments, and tests.
* API modules and tests still import codec helpers through `compute.projection.propagate`; panel tests and experiments still import engineering helpers through `panel.build`.
* `compute.config` and `api/config.py` are explicitly out of scope for this follow-up.

## Approach

* Work in: `compute/`, especially `mu_forecast/panel/`, `projection/`, `jobs/`, `analysis/`, `experiments/`, and their tests.
* Entry point / primary change: replace imports whose imported symbol is a direct alias of another module's implementation.
* Build a small, reviewed inventory of direct aliases and their consumers (including multiline imports); distinguish true façade aliases from functions implemented by the imported module and from intentional package-level APIs.
* Migrate panel consumers to `availability`, `engineering`, `sources`, or `compute.time` as appropriate; in particular, replace `ERCOT_TZ`, CT-boundary, DAM-close, history-cutoff, calendar, and source-panel imports that currently pass through `panel.build`.
* Migrate projection consumers to `projection.codecs`, `projection.sampling`, and `sf_map.storage.maps` when they import aliases rather than `propagate_window` or other projection logic implemented in `propagate.py`.
* Replace legacy `compute.config.PG_DSN` imports with `shared.settings.settings.pg_dsn`, preserving each command's existing DSN behavior.
* Migrate API and test imports of artifact codecs to `projection.codecs`; retain only `propagate_window` and its required local dependencies in `projection.propagate`.
* Migrate panel-engineering consumers to `panel.engineering`, then remove `panel.build`'s compatibility assignments and qualify its internal calls through the owning modules.
* Extend the import-boundary check to scan API as well as compute and assert that removed aliases are no longer attributes of their former façade modules.
* Do NOT touch: `compute/config.py`, `api/config.py`, helper algorithms, timestamp storage/CT delivery-date behavior, SQL, CLI arguments, or artifact formats.

## Acceptance

* [x] Internal production consumers no longer import reviewed one-line aliases through `panel.build`, `projection.propagate`, or `compute.config`; imports resolve to the owning module.
* [x] `panel.build` and `projection.propagate` imports remain only for implementations those modules actually own (for example `build_panel` and `propagate_window`) or an explicitly documented compatibility exception.
* [x] Existing compatibility import paths continue to resolve, and targeted DST/time, panel, projection, daily-forecast, grading, and settings-consumer tests pass.
* [x] The import-boundary check fails when a newly reviewed indirect alias is imported through an intermediary module.
* [x] `panel.build` exposes only panel-building behavior it owns, and every production or test consumer imports availability, engineering, or sources directly.
* [x] `projection.propagate` exposes only propagation behavior it owns, and API plus test consumers import codecs directly.
