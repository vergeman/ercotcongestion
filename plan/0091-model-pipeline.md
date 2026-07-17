# 0091 - model-pipeline

Type: refactor
Branch: refactor/0091-model-pipeline

## Goal

* Add `compute/sf/config.py` as the single source of truth for the SF operating point (`WINDOW_DAYS=240`, `REFIT_DAYS=7`, `RIDGE_LAMBDA=1.0`, `MIN_HOURS=25`).
* Rewire `sf/fit.py`, `sf/runner.py`, `sf/eval.py`, `mu/score.py`, `mu/geo.py`, `mu/weather.py` to import the operating point from `config` instead of local literals/defaults.
* Document the model-build runbook, the test-suite commands, and the known cadence seam + redundancies in `compute/README.md`.

## Context

* The operating point was copy-pasted across the μ modules and was a non-default CLI override on the SF side (`fit` λ=1e-1, `runner`/`eval` window=60), kept correct only by cronjob flags.
* Serving/display phase; modeling frozen. Consistency-only change, no behavior change on the deployed paths.

## Approach

* Work in: `compute/sf/config.py` (new), `compute/sf/{fit,runner,eval}.py`, `compute/mu/{score,geo,weather}.py`, `compute/README.md`, `ops/deploy/jobs/map_refresh_cronjob.yml`.
* Entry point / primary change: `compute/sf/config.py`.
* `config.py` defines the four constants; `fit.py` re-exports `RIDGE_LAMBDA`/`MIN_BINDING_HOURS` from it; `runner`/`eval` set CLI defaults from it; μ modules import `WINDOW_DAYS`/`REFIT_DAYS`/`LAM`/`MIN_HOURS` from it.
* Update the `map_refresh_cronjob.yml` comment (flags are now belt-and-suspenders).
* `README.md`: `## Tests` (docker compose pytest), `## Runbook` (A one-time npz backfill / B daily forecast / C weekly map), cadence-seam + redundancy notes.
* Do NOT touch: `forecast_day.py`, `propagate.py`, `mu_model.py` logic; `STD_FLOOR`; the cronjob commands.

## Acceptance

* [x] All seven modules resolve to `240/7/λ=1.0/25` (verified import assert).
* [x] `docker compose run --rm --no-deps compute python -m pytest /compute/sf/tests /compute/mu/tests -q` — 207 passed, only the 7 pre-existing `test_forecast_day.py` failures remain.
* [x] `compute/README.md` has a `## Tests` section, the runbook, and the redundancy/seam notes.
