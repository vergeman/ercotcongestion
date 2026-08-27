# 0169 - Deterministic nodal forecast

Type: refactor
Branch: refactor/0169-deterministic-nodal-forecast

## Goal

* Serve one deterministic nodal congestion forecast, `point = −(E_mu · SF)`, rather than simulated P10/P50/P90 bands.
* Make the Map, node DetailCard, Matrix contributions, API, persisted forecast panel, and point-grade all use that same deterministic quantity.
* Remove the live residual-pool artifact dependency and retire band-only artifacts, metrics, and documentation.

## Context

* `/matrix/frame` already exposes deterministic `forecast_mu = E_mu = p_bind × mu_gbm` and deterministic `−SF × E_mu` contributions, while Map and node-detail reads use the unrelated simulated `forecast_nodal.p50`.
* P10/P50/P90 are not displayed as forecast uncertainty to users; P50 is the only simulation percentile consumed by Map/Brief/API, while P10/P90 are retained for grading only.
* Live comparison against realized congestion found P50 only modestly better than `point`: h1 trailing-90-day MAE $3.185 vs $3.229/MWh (1.36%); its high-realized-congestion-day advantage was 4.64% across nine h1 days. This is not enough demonstrated value for the unscheduled `mu_preds.npz` residual-pool dependency and the resulting model/UI inconsistency.
* The historical `mu_preds.npz` walk-forward artifact remains useful for offline μ evaluation, but must no longer be required by daily serving.

## Approach

* Work in: `compute/projection/`, `compute/jobs/`, `compute/forecast_store.py`, `compute/artifacts.py`, `db/migrations/`, `api/`, `web/src/`, `docs/Scoring.md`, and `compute/README.md`.
* Entry point / primary change: replace the sampled branch of `compute.projection.propagate.propagate_window` with a deterministic `E_mu` → SF projection that constructs a point-only nodal panel.
* Commit 1 — deterministic compute and artifacts:
  * Remove `eps`, `n_draws`, `rng`, `residual_pool`, `draw_congestion`, and percentile generation from the serving projection path; compute `E_mu` once from `wp`, then compute `point = −(E_mu @ SF)` directly.
  * Reduce `NodalPanel`, its NPZ codec/accumulator, `ForecastResult`, and `forecast_store.nodal_to_db` to the point-only forecast shape. Preserve the SF+μ artifact unchanged: it is the canonical deterministic input for Matrix, Brief analysis, and constraint rollups.
  * Remove `daily_forecast`'s `preds_path`, `load_preds`, `N_DRAWS`, residual-pool loading, and associated CLI/config/run-log surface. A daily forecast must no longer read `runs/<run-id>/mu/mu_preds.npz`.
  * Rework `backfill_nodal` to project historical walk-forward μ predictions deterministically. Keep the μ prediction artifact for offline μ scoring/backtests, but remove residual sampling, `mu_bands_weekly.csv`, and any band-only rerank/scoreboard handoff from the serving/backfill contract.
* Commit 2 — persistence, grading, and database retirement:
  * Add a forward-only migration that drops `forecast_nodal.p10`, `.p50`, and `.p90`; retain `point` and do not rewrite historical forecasts before the migration. Existing rows already contain the deterministic value needed for continued serving.
  * Retire `coverage80`, `band_width`, and `pinball` from daily/weekly scoreboards, their loaders, response schemas, tests, and documentation; point metrics remain `score_matrix(Y, point)` and must be unchanged.
  * Update `grade_day` to load and score only `point`; delete `band_metrics` use and its P10/P50/P90 requirement. Retain SF coverage and all non-band grade metrics.
  * Define the operational cleanup sequence: deploy deterministic readers/writers and database migration together; retain/archive the old PVC prediction/band files until the rollout is verified, then remove only artifacts no longer used by offline evaluation.
* Commit 3 — API and UI contract:
  * Replace the `/forecast_range` P10/P50/P90 payload with one explicitly named deterministic congestion field; select `forecast_nodal.point` in `api/forecast.py` and update FastAPI/Pydantic schemas, TypeScript types, API tests, and generated/client fixtures.
  * Change Map data hooks, HeroMapPreview, forecast/market error calculations, and `_node_market_state` to consume the deterministic field/`forecast_nodal.point`, never P50.
  * Keep `/matrix/frame`'s `forecast_mu` and deterministic contribution calculation unchanged; update comments and tests to assert that Matrix, node detail, and Map reconcile as `−SF × E_mu = forecast_nodal.point` on the same cursor hour.
  * Do NOT touch: the two-head μ fit, target encoding, daily CT/DST boundaries, SF-map fitting/causality, the SF+μ artifact schema, forecast horizon semantics, or Brief's separate historical `settled_history_p10/p50/p90` whiskers.
* Commit 4 — documentation and verification:
  * Remove descriptions of user-facing forecast bands, P50 map fill, residual-pool freshness, and `mu_bands_weekly.csv`; document the deterministic forecast equation and the offline-only role of walk-forward μ predictions.
  * Record the above 90-day and high-congestion-day P50-versus-point comparison in the decision context so the removed uncertainty path is auditable rather than silently discarded.
* Commit 5 — remediation of the double-check findings (gaps left by commits 1–4):
  * `compute/jobs/backfill_artifacts.py` was overlooked — it writes production-equivalent `forecast_nodal` rows through the same `forecast_day`/`persist_forecast` path (runbook Step 4, the per-day artifact that lights up `/map/constraints/ranked` over history), but still imports `N_DRAWS` from `compute.projection.sampling` and calls `forecast_day(..., n_draws=args.draws, preds_path=args.preds)`. `forecast_day` no longer accepts either, so the job raises `TypeError` on its first day. Remove the `N_DRAWS` import, the `--draws`/`--preds`/residual-pool CLI surface, and the `n_draws=`/`preds_path=` call arguments — mirroring the `daily_forecast` cleanup from Commit 1. (No unit test caught this: `test_backfill_artifacts.py` covers only the fire-time helpers, and its docstring states `main()` is exercised by the runbook, not the suite.)
  * Update the band-contract tests left unmodified against the point-only API (Commits 1–2 changed the code but not these callers), so the point-only contract is actually covered and green:
    * `compute/mu_forecast/tests/test_propagate.py` (13 failing) — still uses the old positional `propagate_window(…, eps, n_draws, rng)`, constructs `NodalPanel(p10=, p50=, p90=)`, calls `walk(n_draws=, seed=)`, and asserts on `panel.p10/.p50/.p90`, `coverage80`, `band_width`. Rewrite against the deterministic `propagate_window`/point-only `NodalPanel`/`walk` signatures.
    * `compute/mu_forecast/tests/test_grade_day.py` (1 failing: `test_model_carries_live_bands_comparators_do_not`) — asserts band metrics on the `model` source; drop the band expectations, keep the point-metric and SF-coverage assertions.
    * `api/tests/test_scoreboard_daily.py` (1 failing: `test_daily_serves_all_sources_with_bands_on_model_only`) — expects `coverage80` in the daily payload; retire the band assertions to match the point-only scoreboard.
  * Correct the two remaining user-facing labels that still read `Forecast (P50) Congestion` — `web/src/components/matrix/MatrixReadDetail.tsx` and `web/src/components/map/DetailCard.tsx` — plus the stale `P50` code comments in `web/src/api/types.ts`, `web/src/workspaces/MapWorkspace.tsx`, `web/src/lib/colors.ts`, and `web/src/components/layout/Header.tsx`. Leave Brief's `settled_history` p10/p90 whiskers untouched.
  * Remove the stray editing marker accidentally committed to `compute/README.md` (`-- pausing here because we want to remove to p10/p50/p90 simulated value`) and any residual band language it flags.
  * Not in scope — verified pre-existing on `master`, unrelated to this refactor: `api/tests/test_analysis.py` (3 grade/settlement fixtures) and `api/tests/test_openapi.py` (2 run-id parameter checks) fail independently of the band removal.

## Acceptance

* [x] Daily `forecast_day` produces and persists deterministic point congestion without loading `mu_preds.npz`, sampling residuals, or allocating Monte Carlo draws.
* [x] `forecast_nodal`, its NPZ codec, `/forecast_range`, Map, Hero preview, and node DetailCard expose/use only the deterministic congestion value; no production source refers to `forecast_nodal.p10`, `.p50`, or `.p90`.
* [x] Matrix `forecast_mu`/contributions and the Map/node forecast reconcile to `−SF × E_mu` for the same day, hour, and settlement point.
* [x] `grade_day` continues to produce the same point-metric family from `point`; band-only metrics and the weekly band CSV are retired from scoreboards and APIs.
* [x] Existing deterministic rows can be served without a forecast/model rerun before the migration drops legacy percentile columns; focused compute, API, and web tests cover the point-only contract and pass.
* [x] `backfill_artifacts` runs the per-day path with no `N_DRAWS`/`--draws`/`--preds`/residual-pool surface and no `n_draws=`/`preds_path=` arguments to `forecast_day` — it neither imports `compute.projection.sampling` nor raises `TypeError` on its first day.
* [ ] `test_propagate.py`, `test_grade_day.py`, and `api/tests/test_scoreboard_daily.py` are updated to the point-only contract and pass; the full compute and API suites are green except the pre-existing `test_analysis.py`/`test_openapi.py` failures documented above. (Focused suites pass; the full compute run still has additional failures to audit.)
* [x] No user-facing label or served string reads `P50`; only Brief's `settled_history` whiskers retain percentile wording, and no stray editing markers remain in `compute/README.md`.
