# 0187 - scoreboard-job-boundaries

Type: refactor
Branch: refactor/0187-scoreboard-job-boundaries

## Goal

* Rename the weekly scoreboard importer to `backfill_scoreboard.py` and retain its existing import-and-upsert behavior.
* Place scoreboard-only comparison logic in the API scoreboard service rather than the nodal-backfill job.
* Rename the served-forecast grader to `grade_forecast_day.py` and make its scoreboard-only role explicit.

## Context

* `load_scoreboard.py` only copies precomputed weekly backtest scores into `scoreboard_weekly`, so `backfill_scoreboard.py` describes its operational role more accurately.
* Tracked CronJob manifests and shell scripts contain no direct `load_scoreboard` or `grade_day` module invocation: the former is manual, while forecast CronJobs reach the latter through `daily_forecast.py`.
* `existence_test` has one production caller, `api/services/scoreboard.py`; its only non-API consumers are `compute/mu_forecast/tests/test_propagate.py` tests.
* `grade_day.py` calculates rows for `scoreboard_daily`; Brief grading remains separately owned by `materialize_brief_grade.py`.

## Approach

* Work in: `compute/jobs/`, `api/services/`, `compute/mu_forecast/tests/`, and scoreboard-facing documentation.
* Entry point / primary change: `git mv compute/jobs/load_scoreboard.py compute/jobs/backfill_scoreboard.py` and `git mv compute/jobs/grade_day.py compute/jobs/grade_forecast_day.py`.
* Update Python module imports, module-qualified CLI examples, logger names, error/help text, test module imports and filenames, and tracked documentation references from `load_scoreboard` to `backfill_scoreboard` and from `grade_day` to `grade_forecast_day`; preserve the existing public function names and command arguments unless a caller requires otherwise.
* Update `compute/jobs/README.md`'s job inventory to list both new filenames and their callers. Re-scan `ops/deploy/jobs/`, `ops/deploy/*.sh`, and other tracked shell scripts after the renames; update any discovered invocation, with the expected current result of no direct scoreboard-loader or standalone-grader script change.
* Move `existence_test` unchanged into `api/services/scoreboard.py` as a private scoreboard helper (for example `_beats_persistence`), call it from `_build_splits`, and remove it from `compute/jobs/backfill_nodal.py` so the job no longer carries API-only policy.
* Repoint the existing propagation test to the API helper or relocate its small metric-comparison coverage to a scoreboard-service test; ensure the job tests retain only nodal-backfill behavior.
* Add a concise source comment/docstring in `grade_forecast_day.py` stating that it calculates scoreboard grades for served forecasts and does not calculate Brief grades; leave Brief materialization in `materialize_brief_grade.py` and its existing `daily_forecast.py` call untouched.
* Do NOT touch: score formulas, `scoreboard_weekly` / `scoreboard_daily` schemas, forecast CronJob schedules, or Brief-grade calculations.

## Acceptance

* [ ] `compute/jobs/load_scoreboard.py` and `compute/jobs/grade_day.py` are absent; their `backfill_scoreboard.py` and `grade_forecast_day.py` replacements run with the current CLI arguments.
* [ ] All tracked imports, CLI/documentation references, logs, and user-facing job guidance use the new module names; `compute/jobs/README.md` accurately describes them.
* [ ] No tracked CronJob or shell script retains an old direct invocation; forecast CronJobs continue to reach the grader through `daily_forecast.py`'s updated import.
* [ ] `existence_test` is removed from `compute.jobs.backfill_nodal`; the API owns and tests the same strict three-metric comparison used for weekly splits.
* [ ] `grade_forecast_day.py` explicitly distinguishes scoreboard grading from Brief grading, and the targeted scoreboard, propagation, and daily-forecast grading tests pass.
