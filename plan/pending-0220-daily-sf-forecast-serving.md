# pending-0220 - daily-sf-forecast-serving

Type: feat
Branch: feat/0220-daily-sf-forecast-serving
Depends on: 0219-scoreboard-served-sf-consistency
Status: Preserved for possible future implementation; not currently scheduled

## Goal

* Replace the weekly SF used for forecast projection with one immutable, causal SF fit per CT delivery day.
* Make H2 create and H1 reuse the same daily SF artifact, then let the 0219 grading contract project every comparator through that exact served matrix.
* Validate and backfill the daily-cadence product under new run identities without overwriting the historical weekly-served audit trail.

## Context

* Assume plan 0219 is complete: live and historical daily grading no longer fits its own SF and instead uses the exact `forecast_sf_artifact` stored with each forecast. Comparisons are therefore internally consistent, but the served model SF still comes from the weekly `map-v1` refresh.
* ERCOT's NP4 constraint/shadow-price history changes daily. A weekly refit delays admission of a newly observed constraint after it crosses the existing 25-hour eligibility threshold, potentially omitting a material electrical footprint for several delivery days.
* The SF estimator is already causal over `[D-240d, D)` and can retain the 25-hour screen at daily cadence. The screen—not the cadence—controls when a new key has enough history.
* A daily SF fit is small relative to the full μ forecast: observed grading-time fits are roughly tens of seconds, while a full historical μ forecast replay is roughly 8–9 minutes per day/horizon. Map-only history should take hours serially; a faithful full forecast backfill can take days.
* Stored model `E_mu` is restricted to the SF vocabulary served at the time. It cannot faithfully reconstruct daily-SF forecasts for constraints omitted by the old weekly matrix, so any complete counterfactual forecast history must rerun the μ forecast rather than merely multiply old `E_mu` by a new SF.
* The existing weekly `map-v1` job also maintains Explorer geography and full map evaluation. This migration changes forecast-serving SF cadence only; it does not make that heavier Explorer pipeline daily or change the μ model's weekly geography-derived input features.
* Sep. 14–20, 2026 is a material counterexample to treating daily cadence as an automatic fix: OOS SF R² was −0.139 while stability remained 0.680, because only 61.8% of realized absolute μ mass was represented by the prior fit. The largest omitted key, `215T215_1 | SGIDLIN8`, had zero positive-shadow-price hours in the preceding 240 days, then bound for 58 hours in the scored week. A daily refit could admit it only after it accumulated 25 prior binding hours; it cannot explain its first binding hours.

### Decision gate — resolve before implementation

Daily refits reduce the wait *after* a constraint crosses the 25-hour screen, but do not solve a genuinely novel or abruptly active constraint. They also repeatedly refit on nearly the same 240-day sample, which may add coefficient churn/noise without improving the first-day response. Before starting Commit 1, explicitly choose whether the objective remains daily cadence, or whether it should instead be a targeted novelty/admission policy (for example, an expedited but strongly regularized path for material new keys) while retaining weekly serving. The shadow evaluation must compare those options on: first-appearance/first-25-hour coverage, OOS reconstruction, coefficient stability, and downstream Scoreboard impact; do not promote daily cadence merely because it reduces scheduled-refresh latency.

## Approach

### Commit 1 — Add a canonical daily forecast-SF artifact

* Work in: a new daily-SF service under `compute/sf_map/`, `compute/sf_map/storage/`, shared settings, and focused SF/storage tests.
* Entry point / primary change: implement `load_or_fit_daily_sf(conn, delivery_date, run_id)` using the existing `implied_shift_factors()` math, `WINDOW_DAYS=240`, `LAMBDA=1.0`, and `MIN_HOURS=25` over the strict causal interval `[D-240d, D)`.
* Define `D` and its one-day score interval by America/Chicago delivery-day boundaries, including 23- and 25-hour DST days. Store the exact UTC instants in `sf_window_meta`; do not infer a delivery day by adding a fixed 24 hours.
* Give forecast-serving maps a dedicated identity such as `forecast-sf-daily-v1`, configured separately from the Explorer's weekly `MAP_RUN_ID`. Reuse `sf_window_meta` and `sf_window_artifact` so existing provenance and fit-metadata lookups remain valid; do not invent provenance that lacks a corresponding metadata row.
* Key exactly one canonical matrix to each `(daily_map_run_id, D)`. The first eligible consumer may calculate it, but persistence must be immutable: an existing artifact is reused, and a conflicting recomputation/hash is a hard error rather than a silent overwrite.
* Record window boundaries, row/key counts, clipped coefficients, in-sample fit R², and creation duration. Keep post-delivery OOS diagnostics nullable until realized data exists, and do not label adjacent highly overlapping daily windows with the existing weekly stability statistic unless that statistic is explicitly redefined.
* Apply the same finite-value, non-empty, minimum-history, and predicted-μ-mass coverage guards used by forecast serving. Emit admitted, dropped, and newly admitted constraint counts so a cadence change is operationally observable.
* Make creation race-safe with an insert-or-verify path. Ensure a failed forecast publication cannot leave a promoted forecast pointer referencing an absent daily-map artifact.
* Test strict no-lookahead boundaries, 25-hour admission, CT DST windows, deterministic round trips, load-after-create behavior, conflicting-write rejection, and two consumers resolving the same matrix/hash.
* Do NOT touch: the weekly `map-v1` refit, Explorer geography/artifacts, μ feature construction, Scoreboard formulas, or the plan-0219 grading contract.

### Commit 2 — Serve both forecast horizons through the daily artifact

* Work in: `compute/jobs/daily_forecast.py`, `compute/forecast_store.py`, forecast job configuration/manifests, and focused forecast/publication tests.
* Replace “latest causal weekly map” resolution with an exact delivery-day lookup of `forecast-sf-daily-v1`. If the canonical daily artifact is absent, fit it in memory from data strictly before `D` and persist it with the forecast in a transaction-safe publication path.
* Have the first H2 run for `D` create the canonical daily SF after the existing `D-1` DAM-publication freshness gate. Require H1 to load the same canonical artifact; database corrections between horizons must not change the SF and confound the H2-versus-H1 comparison.
* Continue persisting an exact SF copy in each horizon's `forecast_sf_artifact`, with provenance pointing to the canonical daily `sf_window_meta`/`sf_window_artifact`. Assert that H1 and H2 artifact SF hashes match for the same run/date even though their μ fits and `E_mu` may differ.
* Preserve the existing projection order: align forecast `E_mu` to the admitted daily SF keys, calculate nodal congestion, validate coverage, write forecast rows/artifacts, and move `forecast_current` only after all required data exists.
* Introduce an explicit rollout setting for weekly versus daily forecast SF, default it to weekly during shadow validation, and fail closed on a requested daily fit. Do not silently fall back to the weekly map when the daily artifact is missing or invalid.
* Publish the daily-cadence product under a new forecast/model run ID. Never rewrite historical `mu-all-v1` forecasts or reuse a run ID across the weekly/daily methodology boundary.
* Keep `grade_forecast_day()` unchanged: by plan 0219 it automatically gives model, Oracle, persistence, climatology, and null the daily served matrix once the forecast artifact changes.
* Add tests for H2 create/H1 reuse, identical per-horizon SF hashes, different horizon `E_mu`, missing/invalid-map failure, transaction rollback, no weekly fallback, provenance metadata resolution, and pointer-last promotion.

### Commit 3 — Build and evaluate daily-SF history before promotion

* Work in: a new `compute/jobs/backfill_daily_sf.py`, evaluation/reporting helpers, job documentation, and focused backfill tests.
* Add a resumable map-only command with explicit run ID, inclusive CT date range, dry-run/write modes, per-day commits, skip/verify behavior for existing artifacts, `--stop-on-error`, and a final inventory of created, reused, ineligible, and failed days.
* Evaluate weekly and daily SF on the same delivery days, realized μ/congestion, nodes, and metric formulas. Report fit/OOS R², represented absolute μ mass, node coverage, newly admitted keys, time-to-admission after the 25-hour threshold, and score deltas by footprint size rather than relying on aggregate R² alone.
* Run a representative recent shadow period first. Require the daily candidate to improve admission latency and coverage without a material holdout or Scoreboard regression; record the thresholds and resulting report before enabling the live switch.
* Do not treat the map-only backfill as a forecast backfill. It validates the estimator and produces canonical daily maps, but it does not create counterfactual forecasts or Scoreboard rows.
* Add a non-promoting candidate mode to historical forecast publication so a new daily-SF run can write keyed `forecast_nodal` and `forecast_sf_artifact` rows without changing `forecast_current`. Live publication remains promoting; shadow/backfill publication must be explicitly non-promoting.
* For faithful daily-SF history, rerun the full μ forecast for each requested day/horizon against the canonical daily artifact. Never reuse old weekly-filtered `E_mu` as if it covered newly admitted constraints. Make the replay resumable, independently scoped to H1/H2, and safe to parallelize across non-overlapping dates.
* Regrade completed candidate forecasts with the plan-0219 `backfill_scoreboard_daily` path. Keep legacy weekly rows immutable, expose the new run/methodology boundary, and never splice weekly- and daily-SF metrics under one run identity.
* Document runtime expectations and capacity controls: map-only history is expected to be hours serially, while a full history is expected to be on the order of 8–9 minutes per date/horizon before parallelism. Start with the representative validation range, then choose the full production range from measured throughput.
* Test dry-run non-mutation, interrupted/rerun convergence, artifact verification, per-day rollback, no-pointer candidate publication, and rejection of attempts to derive a full forecast solely from legacy `E_mu`.

### Commit 4 — Cut over, monitor, and preserve the weekly Explorer map

* Work in: deployment manifests/configuration, `compute/jobs/README.md`, `docs/METRICS.md`, operational reconciliation queries, and relevant API/web methodology copy.
* Deploy daily-map support in weekly mode, materialize and evaluate the shadow range, backfill the chosen candidate forecast range, and only then switch the new live run to daily mode. Keep an explicit rollback to weekly mode/new-run publication during the soak period rather than mutating already served rows.
* Continue the weekly `ercot_map_refresh` for Explorer overview, geography, and long-form map diagnostics. Label the Explorer's weekly structural map separately from a forecast day's exact daily served artifact so users do not assume they are interchangeable.
* Update methodology copy to state that one daily SF is fit from information available before `D`, shared by H2/H1, embedded in each forecast artifact, and held fixed across all plan-0219 Scoreboard sources for that forecast key.
* Add monitoring for fit duration, artifact age/existence, fit window bounds, admitted/dropped/new keys, μ-mass coverage, H1/H2 SF-hash equality, provenance resolution, forecast failures, and Scoreboard completion.
* Add a reconciliation check that every promoted daily-cadence forecast has a canonical daily map row, matching canonical and per-horizon SF hashes, valid provenance, and the expected plan-0219 source rows after settlement.
* After the soak period, make daily mode the production default and remove the forecast job's dependence on weekly-map age. Retain the weekly map job and its alerts for Explorer until a separately evaluated plan changes that product.

## Acceptance

* [ ] Exactly one immutable causal SF matrix is stored for each daily-cadence run/delivery date using `[D-240d, D)` and the existing 25-hour eligibility rule, with correct CT DST boundaries.
* [ ] A constraint becomes eligible on the first delivery day after its pre-`D` history reaches the threshold; admission no longer waits for the next weekly refresh.
* [ ] H2 creates or resolves the daily matrix and H1 reuses the same canonical artifact; their stored SF matrices/hashes match for a run/date while their μ forecasts remain horizon-specific.
* [ ] Daily forecast publication fails closed when the exact daily map cannot be fit, loaded, validated, or persisted. It never silently substitutes the weekly map, and `forecast_current` moves last.
* [ ] Every daily forecast artifact has resolvable `sf_window_meta`/`sf_window_artifact` provenance, and all plan-0219 Scoreboard sources use that exact served matrix without another fit.
* [ ] The daily product uses new map and forecast/model run identities; legacy weekly forecasts, artifacts, grades, and pointers remain auditable and are not rewritten in place.
* [ ] The map-only backfill is resumable and produces a paired daily-versus-weekly validation report. Promotion thresholds cover admission latency, μ-mass/node coverage, OOS fit, footprint-sensitive cases, and Scoreboard deltas.
* [ ] Any historical daily-SF forecast/Scoreboard backfill reruns the μ forecast and supports non-promoting publication; it does not claim full fidelity from legacy weekly-filtered `E_mu`.
* [ ] Weekly `ercot_map_refresh` continues to serve Explorer/geography, and product/docs clearly distinguish that structural weekly map from the exact daily forecast-serving map.
* [ ] Focused SF, storage, forecast, backfill, grading, provenance/API, and deployment tests pass, and production reconciliation confirms canonical/per-horizon hash equality and complete post-settlement grades.
