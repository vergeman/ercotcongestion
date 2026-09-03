# 0202 - self-contained-scoreboard-backfill

Type: refactor
Branch: refactor/0202-self-contained-scoreboard-backfill

## Goal

* Make `compute.jobs.backfill_scoreboard` run the complete historical walk-forward, evaluation, and `scoreboard_weekly` publication from dates and a model run ID.
* Make all μ prediction, score, and chunk files job-owned temporary scratch data, cleaned after success or failure.
* Remove the legacy persistent `runs/<run-id>/mu/` artifact contract and its file-based nodal seed path.

## Context

* `backfill_scoreboard` currently only imports a precomputed `mu_score_weekly.csv`; producing it requires separate backtest and evaluation commands plus `mu_preds.npz`.
* The live/API forecast backfill is already independent: the current `backfill_artifacts` job writes `forecast_nodal` and `forecast_sf_artifact` directly to Postgres; its name should change with this cleanup.
* `model.backtest` already bounds memory with prediction chunks, and model folds already use `MU_SPILL_DIR` for panel and bind-matrix spills; these are suitable job-owned scratch mechanisms rather than durable run artifacts.
* `scoreboard_weekly` and forecast tables retain `run_id` as durable model provenance. This plan removes filesystem run state, not database provenance.

## Approach

* Work in: `compute/jobs/backfill_scoreboard.py`, `compute/mu_forecast/model/backtest.py`, `compute/evaluation/mu.py`, `compute/mu_forecast/model/`, `compute/jobs/backfill_nodal.py`, `compute/artifacts.py`, tests, and compute/artifact documentation.
* Entry point / primary change: extend `python -m compute.jobs.backfill_scoreboard` with the historical walk inputs (`--run-id`, `--start`, `--end`, feature/model options, and bounded chunk controls) and make it publish the computed rows itself.
* Extract callable backtest and μ-evaluation stages whose values flow in memory where practical. Keep existing walk-forward feature, grid, causal-vintage, score, and metric semantics byte/row equivalent to the present pipeline.
* Run any required large prediction chunks and combined prediction representation inside a unique `TemporaryDirectory` under `MU_SPILL_DIR` when configured (otherwise the system temporary directory). Reuse the existing chunked-walk and spill conventions; use `try`/`finally` cleanup so no `mu-pred-chunks`, prediction NPZ, score CSV, Arrow panel, or bind-matrix file is retained by the job.
* Make the scoreboard persistence layer accept computed score rows/DataFrames, not a score-file path. Preserve the existing run-scoped delete-and-COPY transaction, source IDs, score formulas, and `scoreboard_weekly` schema.
* Make the normal `backfill_scoreboard` contract singular: it must not accept or emit reusable prediction/score artifact paths. Remove the score-file importer mode rather than retaining it as an alternate production workflow. Audit the completed run through durable `scoreboard_weekly` rows, its `run_id`/week/source keys, and structured job logs; do not make filesystem intermediates an audit contract.
* If a developer-only backtest/evaluation CLI remains useful, keep it outside `compute/jobs`, require explicitly supplied paths, and ensure no compute job or default CLI path can discover or consume its output. Do not document it as an operational backfill input.
* Remove `compute.jobs.backfill_nodal` and its `forecast/mu_nodal.npz` seed/reload workflow once its remaining callers are confirmed absent. Historical forecast/API coverage must continue through the renamed `backfill_forecasts` job.
* Rename `compute.jobs.backfill_artifacts` to `compute.jobs.backfill_forecasts`. Preserve its production-equivalent per-day behavior, horizons, date range, causal fire-time reconstruction, skip/resume semantics, and DB publication; update imports, tests, documentation, and hand-run instructions in the forecast CronJob manifests. The new name refers to the durable forecast products, not temporary files or encoded database blobs.
* Delete `compute/artifacts.py` after its callers are removed; delete `RunArtifacts`, canonical μ artifact path helpers, and default μ-artifact output plumbing rather than leaving a deprecated artifact abstraction behind. Update tests, CLI help, README/runbook material, and any experiment references; experiments may retain only explicit user-supplied file inputs where still useful.
* Rewrite `docs/ARTIFACTS.md` at the same time: remove the four retired filesystem artifacts and describe the durable Postgres forecast state (`forecast_nodal`, `forecast_sf_artifact`, and their `run_id`/delivery-day/horizon keys), plus the distinction between job-owned temporary spill/chunk files and persistent data. Do not preserve a historical artifact catalog merely for compatibility.
* Do NOT touch: daily forecast/model mathematics, `backfill_artifacts` behavior, Postgres forecast artifact schemas, `forecast_current` publication order, Scoreboard metric definitions/source identities, or the weekly-map spill/PVC deployment contract.

## Commit groups

1. `refactor(scoreboard): make walk-forward publication self-contained` — expose reusable backtest/evaluation values, add the end-to-end `backfill_scoreboard` orchestration, and preserve the existing database transaction semantics.
2. `refactor(backtest): make prediction staging job-owned scratch` — route chunk and spill files through a unique cleanup scope, preserve bounded-memory behavior, and retain explicit experiment exports only where justified.
3. `refactor(artifacts): retire legacy mu run files and nodal seed` — rename `backfill_artifacts` to `backfill_forecasts`, remove `backfill_nodal`, delete `compute/artifacts.py` / `RunArtifacts`, remove default artifact paths, rewrite `docs/ARTIFACTS.md`, and delete obsolete tests after a full dependency scan.

## Acceptance

* [ ] One `backfill_scoreboard` invocation from `run_id`, date range, and model options performs the historical walk-forward, evaluates it, and commits the expected `scoreboard_weekly` rows without accepting or requiring a prediction or score artifact path.
* [ ] The new job's rows are equivalent to the current backtest → evaluation → importer pipeline for a fixed fixture/range, including source IDs, week keys, and all screening metrics.
* [ ] Chunked execution remains bounded and uses the existing spill configuration; all job-owned scratch files are removed after both success and a simulated stage failure.
* [ ] `compute/artifacts.py` is deleted, and no production code, default CLI path, or documentation references `mu_weekly.csv`, `mu_preds.npz`, `mu_score_weekly.csv`, `forecast/mu_nodal.npz`, `RunArtifacts`, or `compute.artifacts`.
* [ ] `compute.jobs.backfill_artifacts` is absent and `compute.jobs.backfill_forecasts` provides its unchanged historical live-forecast behavior; every tracked invocation and runbook uses the new name.
* [ ] `compute.jobs.backfill_nodal` is deleted, including its CLI, tests, documentation, and file-seed/reload modes; historical live forecast coverage is supplied only by `backfill_forecasts`.
* [ ] `docs/ARTIFACTS.md` describes only durable database-backed forecast state and ephemeral job-owned scratch storage; it does not catalog retired filesystem artifacts.
* [ ] No module under `compute/jobs` reads or writes a persistent μ prediction, weekly-metric, weekly-score, or nodal-panel file; a focused import/reference test covers this boundary.
* [ ] `backfill_artifacts`, daily forecast publishing, API reads of `forecast_nodal` / `forecast_sf_artifact`, and live daily grading continue unchanged and pass their focused tests.
* [ ] Focused backtest, evaluation, scoreboard, artifact-removal/import-boundary, and database persistence tests pass; a repository-wide reference scan has only deliberately retained explicit experiment-export compatibility references, if any.
