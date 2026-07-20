# 0003 - live-grading

Type: feat
Branch: feat/0003-live-grading

## Status (2026-07-20) — shipped grade-only; miss-attribution deferred

Scoped down at build time. The **live grade** ships; **miss-attribution is
deferred** as a separate future change. Rationale: the daily grade is small,
high-leverage, and load-bearing for the "live, self-grading" claim (`score_matrix`
on served-vs-realized — two DB reads for the model); miss-attribution is the bulk of
the work, its driver/model buckets are approximations without a counterfactual
re-run, its audience is thin, and it was the *only* reason to touch the production
forecast job. Revisit once the daily grade proves people want the "why".

**Shipped:**

* Migration `db/migrations/35_scoreboard_daily.sql` — `scoreboard_daily` only.
* `compute/jobs/grade_day.py` (NOT `compute/mu/` — `forecast_day` was reorged to
  `compute/jobs/daily_forecast.py`; `grade_day` is its sibling there). Reuses
  `score_matrix` + the `mu_*` source builders + `band_metrics`; fits the baseline
  SF inline, leaving `score.py` untouched.
* **Grading folded into the daily tick, no new CronJob.** `daily_forecast.main`
  calls `grade_day` on the most recent fully-realized, ungraded served day after a
  `--to-db` publish commits — non-fatal (a grade failure never fails the publish or
  moves the pointer; the next tick self-heals via an idempotent, self-selecting
  `resolve_gradeable_date`). New `--no-grade` flag for forecast-only backfills.
* `GET /scoreboard/daily?since` + `DailyPoint`/`ScoreboardDaily` models.
* Tests: `compute/mu/tests/test_grade_day.py` (8), `api/tests/test_scoreboard_daily.py` (6).

**Deferred (NOT built):** the `scoreboard_miss` decomposition, the prediction-time
`forecast_snapshot` table + the `daily_forecast` snapshot write it needed, and
`GET /scoreboard/miss?date`. When it returns it lands as its own migration + endpoint;
migration 35 carries a NOTE at the deferral seam.

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Add the `scoreboard_daily` table (one row per delivery day × source) and a `grade_day(D)` job that grades the served forecast for D against realized DAM SPP. **[SHIPPED]**
* ~~Compute miss-attribution for each graded day — decompose the miss into unforecastable-outage, driver-forecast bust, and model error — from inputs snapshotted at prediction time.~~ **[DEFERRED — see Status]**
* Serve `GET /scoreboard/daily?since` (per-delivery-day grades). ~~and `GET /scoreboard/miss?date` (one day's miss decomposition).~~ **[/miss DEFERRED]**

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* The live half grades yesterday's forecast; it needs Phase 2's `forecast_day` producing `forecast_nodal` panels + a day of realized data (`spec-phase3-scoreboard.md` §1, §8 step 4) — build after Phase 2, unlike the backtest board (0001/0002).
* Grading reuses the **same** metric functions as the backtest — `compute/mu/score.py::score_matrix(Y, Yh)` — so live and backtest numbers are the same currency (spec §2.2).
* Miss-attribution is what turns the scoreboard from a report card into a tool: it requires snapshotting, at prediction time, the driver inputs the forecast actually used (spec §4). **[DEFERRED out of this change — see Status.]**
* Integrity: a flat prediction cannot score — `score.py` declines rows flat across nodes; any live metric must be null-checked against the `null` source before it's trusted (spec §6).

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `db/migrations/` (`scoreboard_daily`), **`compute/jobs/`** (new `grade_day.py` sibling of `daily_forecast.py` — the reorged `forecast_day`; NOT `compute/mu/` as originally written), `api/` (extend the `/scoreboard` module with `/daily`). ~~+ `/miss`~~
* Migration: create `scoreboard_daily(run_id, delivery_date, source, <same metric columns as scoreboard_weekly>, coverage)` per spec §2.2; `run_id` ties each grade to the model version that served it. **[SHIPPED — migration 35; no `regime` column (a 24-h day is too thin for quintile splits, and §2.2's daily key omits it).]**
* `grade_day(D)`: pull the served point forecast for D and realized `C` for D (SPP − system_λ); run `score_matrix(Y, Yh)` for each source available at serve time (model on the served point + live P50 bands; persistence/climatology/oracle/null recomputed on D for context); write one row per source. **[SHIPPED.]** All sources scored on one shared (hours × nodes) matrix = SF-nodes ∩ served-nodes ∩ realized-nodes, so the per-day model−persistence delta is apples-to-apples. ~~snapshot the prediction-time inputs for miss-attribution~~ **[DEFERRED — no snapshot]**. **Not a separate schedule** (as the plan sketched "one day behind `forecast_day`"): the daily tick (`daily_forecast.main`) runs it in-process after publishing tomorrow's forecast, grading the most recent fully-realized ungraded served day — non-fatal, no new CronJob.
* ~~Miss-attribution (spec §4): decompose into **unforecastable-outage** (novel constraint bound with no history — from the Phase-2 novelty flag), **driver-forecast bust** (load/wind/solar forecast at DAM close vs realized), and **model error** (residual); persist alongside the daily grade.~~ **[DEFERRED — see Status. `novelty`/`novel_keys` already exist on `forecast_day`'s output; the deferred piece is snapshotting them + the grade-time decomposition.]**
* Endpoints: `GET /scoreboard/daily?since` ~~and `GET /scoreboard/miss?date`~~; return baselines + oracle (and the `null` tripwire) alongside model on every response (spec §3). **[SHIPPED — /daily only.]**
* Do NOT: redefine the gate or re-measure baselines outside the shared harness (spec §6) — `grade_day` imports `score_matrix` + the `mu_*` source builders, never re-deriving them; do NOT build the web panels here (0004); do NOT alter the backtest tables/endpoints (0001/0002).

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [x] `scoreboard_daily` exists; `grade_day(D)` writes one row per source for a delivery day, with metrics + coverage keyed by `run_id`. *(migration 35; `grade_day` + `persist_grades`)*
* [x] Live grade reconciliation: `grade_day(D)` for an in-sample backtest D reproduces the backtest week's metric for D to tolerance (same `score_matrix`) (spec §7). *(`test_grade_day.py::test_rows_reproduce_score_matrix_on_the_same_inputs` — each source row is byte-equal to `score_matrix` recomputed on the same Y/Yh; the model is proven to use the served `point`, not `p50`.)*
* [x] Null guard: feeding the `null` source scores at chance, not inflated — the metric path still declines flat rows (spec §7). *(`test_null_source_cannot_manufacture_a_screening_score`; `test_daily_serves_all_sources...` at the API layer.)*
* [ ] ~~Each graded day stores a miss decomposition (unforecastable-outage / driver-forecast bust / model error) from prediction-time inputs.~~ **DEFERRED — see Status.**
* [x] `GET /scoreboard/daily?since` returns per-delivery-day grades ~~and `GET /scoreboard/miss?date` returns one day's decomposition~~, each carrying baselines + oracle (and the `null` tripwire) alongside model. *(`test_scoreboard_daily.py`; `/miss` deferred.)*
