# 0219 - scoreboard-served-sf-consistency

Type: fix
Branch: fix/0219-scoreboard-served-sf-consistency

## Goal

* Grade the served model, persistence, climatology, Oracle, and null sources through the exact SF matrix stored with each served forecast.
* Add a range backfill that safely replaces historical `scoreboard_daily` rows without rerunning or rewriting forecasts.
* Make the Scoreboard's SF and Oracle semantics accurate in source descriptions, product copy, and operating documentation.

## Context

* `daily_forecast` projects each horizon through a causal weekly `map-v1` SF and persists that exact matrix in `forecast_sf_artifact` beside `forecast_nodal`.
* `grade_forecast_day.grade_day()` currently fits a separate `[D-240d, D)` SF for persistence, climatology, Oracle, and null; only the model uses the served weekly SF, and the stored artifact is read only for ESSP.
* The mismatch confounds live model-versus-baseline metrics, makes the model row's `sf_coverage` describe the grader-local map, and leaves existing `scoreboard_daily` history under the old contract.
* Forecast rows and artifacts already preserve the historical served products by `(run_id, delivery_date, horizon)`, so correction requires regrading only; both horizons must be handled independently.

## Approach

### Commit 1 — Grade every live source through the served SF artifact

* Work in: `compute/jobs/grade_forecast_day.py`, `compute/projection/codecs.py` if artifact validation needs a shared helper, and `compute/mu_forecast/tests/test_grade_forecast_day.py`.
* Entry point / primary change: make `grade_day()` load and decode `forecast_sf_artifact.sf_npz` for the exact `(run_id, delivery_date, horizon)` before constructing any source score.
* Return or pass the decoded `SF` through the whole grade so baseline projection, ESSP, node selection, and SF coverage all use one in-memory matrix; do not issue a second artifact read for ESSP.
* Remove the grader-local `implied_shift_factors()` call and its congestion fit window. Retain the trailing shadow-price history needed to construct climatology and prior-day persistence, and load realized congestion only for the scored CT day.
* Build the common score universe from served-SF nodes intersected with served forecast nodes and realized nodes. Calculate `sf_coverage` from realized μ mass represented by the served SF rows, then stamp that served-map coverage and common grain on every source row.
* Project Oracle's realized μ, persistence's prior-day μ, climatology's trailing μ estimate, and null μ through the same served `SF`; continue scoring the model from the immutable served `forecast_nodal.point` values.
* Fail before persistence when the keyed artifact is absent, undecodable, empty, non-finite, or inconsistent with its labels. Do not refit or fall back to `map-v1`, because either substitute would change the comparison contract.
* Preserve metric formulas, source IDs, day/horizon keys, and `persist_grades()`'s delete-and-COPY transaction boundary.
* Add a regression fixture where the stored SF deliberately differs from a would-be daily fit; assert every comparator uses the stored matrix, the model uses the served point, and `implied_shift_factors` is no longer called by live grading.
* Add horizon coverage proving h1 and h2 load their own artifacts and can produce different comparator scores when their stored SF matrices differ.
* Do NOT touch: `forecast_nodal`, `forecast_sf_artifact` publication, weekly `map-v1` fitting/cadence, `scoreboard_weekly`, Brief-grade calculations, or forecast pointers.

### Commit 2 — Add an idempotent daily-Scoreboard range backfill

* Work in: new `compute/jobs/backfill_scoreboard_daily.py`, focused job tests under `compute/mu_forecast/tests/`, and `compute/jobs/README.md`.
* Entry point / primary change: add `python -m compute.jobs.backfill_scoreboard_daily --run-id <id> --horizon <1|2> --start YYYY-MM-DD --end YYYY-MM-DD [--to-db]` with inclusive CT delivery dates; require the horizon explicitly so operators deliberately repair both tracks.
* Reuse `grade_day()` and `persist_grades()` directly so historical repair and future daily grading cannot acquire separate score logic. Do not reconstruct forecasts, refit μ heads, or duplicate projection formulas in the backfill.
* Default to a read-only dry run that computes and reports candidate grades. With `--to-db`, grade first, then replace all source rows for one `(run_id, delivery_date, horizon)` and commit that key atomically before advancing.
* Intentionally regrade keys that already contain rows—the existing values are the data being repaired. Make reruns safe and deterministic rather than treating existing `scoreboard_daily` rows as a skip condition.
* Treat absent served forecasts, absent/corrupt SF artifacts, and incomplete realized data as visible per-day failures that leave prior rows intact. Continue by default, add `--stop-on-error`, and finish with counts and date lists for replaced, newly materialized, missing-artifact, ungradeable, and failed keys.
* Open bounded/fresh database scopes as needed for a long run and roll back a failed key before continuing. A process interruption may leave earlier keys committed, and rerunning the same range must safely converge on the same rows.
* Document the production repair as two explicit invocations, one for horizon 1 and one for horizon 2, followed by row-count and missing-artifact reconciliation. Do not add a recurring CronJob: the existing final and preview forecast ticks already invoke the corrected `grade_day()` for future dates.
* Test dry-run non-mutation, exact five-row replacement, per-key rollback on failure, continue/stop behavior, reversed-range rejection, and an interrupted/rerun-equivalent sequence.
* Do NOT touch: forecast artifacts or nodal rows, `forecast_current`, `scoreboard_weekly`, Brief snapshots/grades, or map-refresh state.

### Commit 3 — Correct Scoreboard descriptions and verify the repaired contract

* Work in: `api/services/scoreboard.py`, `docs/METRICS.md`, `compute/jobs/README.md`, Scoreboard web copy in `web/src/features/scoreboard/` and `web/src/components/panels/SidePanel.tsx`, plus focused API/web tests.
* Describe daily persistence and Oracle as projected through the served forecast's SF artifact, not an independently fitted trailing map.
* Replace claims that Oracle is the best possible score or a mathematical ceiling with “Settled-μ Benchmark (Oracle)” language. Explain that it is realized μ conditional on the served estimated map and can lose a rank metric because the map is regularized and incomplete; preserve canonical source IDs and `series_id="oracle"`.
* Update the metric documentation to state that weekly backtest folds hold their fold SF fixed across sources and live grades hold the served artifact SF fixed across sources; both therefore isolate μ-source differences within their own cadence.
* Add an operational verification query/runbook that joins repaired `scoreboard_daily` keys to `forecast_sf_artifact`, checks five source rows per key, checks both horizons separately, and reports artifact holes without modifying them.
* Run the focused grading/backfill/API suites and web typecheck/lint. On a representative production dry run, record old-versus-corrected metric deltas and confirm no forecast, artifact, pointer, weekly-score, or Brief table changes.

## Acceptance

* [x] Future live grading performs no SF fit and uses the exact keyed `forecast_sf_artifact.SF` for model-universe selection, coverage, ESSP, Oracle, persistence, climatology, and null.
* [x] A missing or invalid served SF artifact fails the grade before deleting or writing `scoreboard_daily`; there is no silent weekly-map load or daily-refit fallback.
* [x] H1 and h2 grading load independent artifacts, while all sources within one `(run_id, delivery_date, horizon)` share the same hours, nodes, target, and SF matrix.
* [x] `sf_coverage` and `n_nodes` on the model row describe the served artifact rather than the retired grader-local fit.
* [x] The new range backfill supports dry-run and write modes, explicitly scopes one horizon, atomically replaces five rows per successful key, continues safely after a failed key, and is idempotent on rerun.
* [ ] Running the repair for both horizons changes only `scoreboard_daily`; requires the production repair and reconciliation.
* [x] Historical artifact holes are reported and retain their prior grade rows for operator review rather than being silently refit, deleted, or partially rewritten.
* [x] Scoreboard API/web copy calls Oracle a settled-μ benchmark conditional on the selected map and no longer promises an unattainable mathematical ceiling.
* [ ] Focused compute and API tests plus web typecheck/lint pass; the production dry-run and reconciliation remain operator work.
