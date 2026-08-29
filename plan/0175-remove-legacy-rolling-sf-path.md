# 0175 - remove legacy rolling SF path

Type: refactor
Branch: refactor/0175-remove-legacy-rolling-sf-path

## Goal

* Make bounded chunked fitting the only execution path for `compute.jobs.weekly_map`.
* Remove the callback-based `rolling_sf` full-history walker and its `--chunk-weeks 0` escape hatch.
* Preserve the SF matrices, diagnostics, persistence behavior, and default 32-refit chunk cadence.

## Context

* `--chunk-weeks` already defaults to `32`; the normal map-refresh path loads and fits bounded chunks through `fit_refit_window`.
* The full-history branch is selected only by `--chunk-weeks 0` and is the sole non-test runtime caller of `rolling_sf`.
* A full-history panel is unsafe for rebuild-scale memory usage; every map run must now use a positive bounded chunk size.

## Approach

* Work in: `compute/jobs/weekly_map.py`, `compute/sf_map/model/rolling.py`, `compute/sf_map/storage/persist.py`, focused SF tests, and affected compute documentation.
* Make `--chunk-weeks` strictly positive (`>= 1`), retain `32` as its default, and update its help text to describe the required bounded loading behavior. Remove the legacy-mode wording and reject `0` with an argparse error.
* Delete the `if args.chunk_weeks` / `else` split in `weekly_map.main`; retain the existing schedule discovery, pending-window filtering, chunk loop, `fit_refit_window(...)`, and immediate diagnostics/persistence path as the only runner flow.
* Remove `rolling_sf`, its callback and skip-window API, `Callable` import, and full-history-walker comments from `compute.sf_map.model.rolling`. Retain `RefitWindow`, `_align`, `fit_refit_window`, and `_fit_refit_window_aligned`, which remain the single-window fitting API used by chunks.
* Update persistence and evaluation documentation that names `rolling_sf` to describe the unchanged production fit semantics (`window_end == score_end`) without claiming that a full-history walker is used. Remove the obsolete no-chunk walkthrough from `compute/README.md`; document `--chunk-weeks` in the map-runner reference as required and defaulting to 32.
* Replace callback/walker-specific tests in `compute/sf_map/tests/test_grouped_fit.py` with direct `fit_refit_window` coverage for grouped and ungrouped `RefitWindow` invariants. Keep an equivalence test showing that fitting a bounded interval yields the same SF and fit panels as fitting from a larger panel containing that interval.
* Add CLI-focused coverage proving `weekly_map` retains the default `chunk_weeks == 32` and rejects `--chunk-weeks 0` (and negative values) before connecting to the database.
* Do NOT change the refit-grid math, fit/scoring time boundaries, ridge/grouping behavior, database schema, persistence transaction semantics, or `compute.evaluation.sf` OOS calculations.

## Acceptance

* [x] `weekly_map` has one, positive-chunk-only execution path and no import or call to `rolling_sf`.
* [x] Omitting `--chunk-weeks` uses 32; zero and negative values fail argument validation with a clear message.
* [x] `rolling_sf` and its callback/skip API have no remaining source, test, or documentation references.
* [x] Direct single-window tests preserve grouped/ungrouped `RefitWindow` invariants and bounded-versus-larger-panel SF equivalence.
* [x] Focused SF-map and operating-default tests pass.
