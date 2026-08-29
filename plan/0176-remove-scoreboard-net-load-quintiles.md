# 0176 - simplify scoreboard evaluation contract

Type: refactor
Branch: refactor/0176-simplify-scoreboard-evaluation-contract

## Goal

* Make the Scoreboard an all-hours, screening-only evaluation surface.
* Stop computing, storing, serving, and documenting net-load quintile, pooled R², and MAE scorecard data.
* Remove the weekly-board regime dimension and magnitude columns with forward-only database migrations.

## Context

* The page exposes five net-load buckets and a magnitude toggle, while the live board has no regime dimension and the product is better explained through screening metrics.
* `compute.evaluation.mu` adds bucket slices only for offline score reporting; pooled R²/MAE exist only in the product scorecard path plus a retired R²-dependent verdict.
* `scoreboard_weekly` currently keys rows by `(run_id, week, source, regime)`; both scoreboard tables carry `pooled_r2` and `mae`, while independent model/SF diagnostics also use those metrics.

## Approach

* Work in: `compute/evaluation/mu.py`, `compute/jobs/{grade_day,load_scoreboard,backfill_nodal}.py`, `db/migrations/`, `api/scoreboard.py`, `api/services/scoreboard_headline.py`, `api/models.py`, `web/src/api/`, `web/src/hooks/useScoreboard.ts`, `web/src/features/scoreboard/ScoreboardControls.tsx`, `web/src/pages/ScoreboardPage.tsx`, focused tests, `docs/Scoring.md`, and `compute/README.md`.
* Entry point / primary change: reduce `score_week`/`walk`, `score_matrix`, and the weekly/daily scoreboard contracts to one all-hours row per `(week, source)` carrying Rank rho, Sign Agreement, and Top-Decile Hit only.
* Commit 1 — remove unused evaluation dimensions: delete the optional `regimes` argument, `--no-regimes` CLI flag, `system_panel`/`net_load_regime` loading, bucket-row loop, and bucket reporting from `compute.evaluation.mu`. Keep `net_load_regime` only where experiments/tests independently use it.
* Commit 2 — remove magnitude verdicts and columns: retire `backfill_nodal.gate`, its R²-or-screening R5 output, and `WeeklySplit.gate`; retain the screening-only persistence existence test if the lifetime comparison remains. Delete `pooled_r2`/`mae` from product `score_matrix`, daily grades, weekly CSV loading, headline currencies, API selects/schemas, and TypeScript types. Do not invent replacement thresholds in this refactor.
* Commit 3 — migrate and simplify the contract: remove non-`all` weekly rows, replace the weekly primary key with `(run_id, week, source)`, drop `regime`, and drop `pooled_r2`/`mae` from both scoreboard tables. Do not rewrite/recompute the retained screening values.
* Commit 4 — simplify UI/API/documentation: remove regime parameters/cache keys/selector/tooltip and the magnitude toggle, R² tile, MAE/R² glossary/copy, and regime-dependent empty state. Resolve and serve only the all-hours, screening-only board.
* Update loader/API/compute/frontend tests and deployment verification to prove no regime/magnitude scoreboard fields remain and all three screening metrics still reconcile. Preserve MAE/R² functions and outputs used by offline model training, experiments, and SF diagnostics.
* Do NOT touch: daily forecast fitting, horizon storage/preview jobs, model-calibration metrics, `compute.metrics`, SF-map OOS diagnostics, or experimental net-load analysis outside the product scoreboard.

## Acceptance

* [x] A scoring run emits only all-hours, screening-only scoreboard rows and has no scoreboard regime CLI, R²/MAE computation, or magnitude reporting path.
* [x] `scoreboard_weekly` has primary key `(run_id, week, source)` and neither scoreboard table has `regime`, `pooled_r2`, or `mae`; retained all-hours screening values remain readable.
* [x] `/scoreboard/*`, TypeScript types/cache keys, and the page have no regime parameter, bucket selector, magnitude toggle, R² tile, MAE/R² copy, or gate verdict.
* [x] Offline model-calibration and SF/experiment MAE/R² diagnostics retain their existing contracts.
* [ ] Focused compute, API, migration, and web tests pass; production verification must still show one weekly row per run/week/source after deployment.
