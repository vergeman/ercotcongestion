# 0181 - relocate shared config constants out of evaluation

Type: refactor
Branch: refactor/0181-relocate-shared-config-constants

## Goal

* Stop production jobs from depending on `compute.evaluation` for plain configuration constants.
* Give the `RTC_B` market-break date one source of truth instead of three copies.

## Context

* `compute/jobs/daily_forecast.py` and `compute/jobs/backfill_nodal.py`
  **produce** forecasts; they do no scoring. Yet they import
  `WINDOW_DAYS`/`REFIT_DAYS` (and `RTC_B`, `weeks_from_preds`) from
  `compute.evaluation.mu`, creating a prod→evaluation edge that exists only for
  constants.
* `WINDOW_DAYS`, `REFIT_DAYS`, `RIDGE_LAMBDA`, `MIN_HOURS` already have a proper
  home: `compute/sf_map/config.py:15-18`. `evaluation.mu:48` merely
  **re-exports** them from there — the jobs are reaching through a re-exporter,
  not the source.
* `RTC_B` (the 2025-12-05 structural break) is genuinely misplaced and
  triplicated:
  * defined in `compute/evaluation/mu.py:52` (`RTC_B`),
  * hardcoded again in `compute/experiments/sf/coverage.py` (`RTCB_DATE`),
  * hardcoded a third time in `compute/experiments/sf/grouping_verdict.py`
  (`RTCB_CUTOVER`). One literal date in three files: if it ever moves, all three
  must be found by hand.
* `weeks_from_preds` (imported by `backfill_nodal`) is a real function, not a
  constant — it legitimately lives in `evaluation.mu` and stays there. This plan
  does not touch it.

## Approach

* Work in: `compute/sf_map/config.py`, `compute/evaluation/mu.py`,
  `compute/jobs/daily_forecast.py`, `compute/jobs/backfill_nodal.py`,
  `compute/experiments/sf/coverage.py`,
  `compute/experiments/sf/grouping_verdict.py`, and existing tests under
  `compute/*/tests/`.
* **Constants (window/refit):** repoint `daily_forecast` and `backfill_nodal` to
  import `WINDOW_DAYS`/`REFIT_DAYS` from `compute.sf_map.config` directly.
  Values are identical — this is an import-path change only.
* **`RTC_B`:** add it once to `compute/sf_map/config.py` (the market-date lives
  beside the other domain constants; no new module unless a wider
  market-calendar surfaces later). Have `evaluation.mu` import and re-export it
  for its own callers; repoint `backfill_nodal` to the config source. Replace
  the two experiment literals (`RTCB_DATE`, `RTCB_CUTOVER`) with an import of
  the shared constant, preserving each call site's existing tz handling
  (`coverage.py` localizes per-row; `grouping_verdict.py` wants a UTC-aware
  timestamp).
* Keep `evaluation.mu`'s re-exports so nothing else that imports from it breaks;
  the point is to fix the *jobs'* import paths and de-duplicate the date, not to
  forbid re-export.
* Do NOT change any constant's value, the refit grid, scoring logic, forecast
  safety gates, or schema.

## Acceptance

* [x] `daily_forecast` and `backfill_nodal` import `WINDOW_DAYS`/`REFIT_DAYS`
      from `compute.sf_map.config`, not from `compute.evaluation.*`.
* [x] `RTC_B` is defined exactly once (`compute/sf_map/config.py`);
      `evaluation.mu`, `backfill_nodal`, `coverage.py`, and
      `grouping_verdict.py` all reference that single definition, with per-site
      tz behavior unchanged.
* [x] `grep -rn '2025-12-05' compute/` shows no remaining hardcoded copies of
      the break date outside the single config definition.
* [x] The only remaining `compute.evaluation` import in
      `daily_forecast`/`backfill_nodal` is a genuine function/scorer (e.g.
      `weeks_from_preds`), not a constant.
* [ ] Full compute test suite passes; forecast and backfill jobs produce
      byte-identical output to before (values unchanged).

## Verification

* Focused affected tests passed: `107 passed, 12 skipped`.
* The full compute suite was run with the development environment. It stopped on
  an unrelated existing assertion in `analysis/tests/test_hero_queries.py`, where
  the expected condition summary omits fields returned by the current builder.
  The constants refactor introduced no test failures before that point.
