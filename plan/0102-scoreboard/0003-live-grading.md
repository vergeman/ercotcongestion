# 0003 - live-grading

Type: feat
Branch: feat/0003-live-grading

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Add the `scoreboard_daily` table (one row per delivery day × source) and a `grade_day(D)` job that grades the served forecast for D against realized DAM SPP.
* Compute miss-attribution for each graded day — decompose the miss into unforecastable-outage, driver-forecast bust, and model error — from inputs snapshotted at prediction time.
* Serve `GET /scoreboard/daily?since` (per-delivery-day grades) and `GET /scoreboard/miss?date` (one day's miss decomposition).

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* The live half grades yesterday's forecast; it needs Phase 2's `forecast_day` producing `forecast_nodal` panels + a day of realized data (`spec-phase3-scoreboard.md` §1, §8 step 4) — build after Phase 2, unlike the backtest board (0001/0002).
* Grading reuses the **same** metric functions as the backtest — `compute/mu/score.py::score_matrix(Y, Yh)` — so live and backtest numbers are the same currency (spec §2.2).
* Miss-attribution is what turns the scoreboard from a report card into a tool: it requires snapshotting, at prediction time, the driver inputs the forecast actually used (spec §4).
* Integrity: a flat prediction cannot score — `score.py` declines rows flat across nodes; any live metric must be null-checked against the `null` source before it's trusted (spec §6).

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `db/migrations/` (`scoreboard_daily`), `compute/mu/` (new `grade_day.py` sibling of `forecast_day`), `api/` (extend the `/scoreboard` module with `/daily` + `/miss`).
* Migration: create `scoreboard_daily(run_id, delivery_date, source, <same metric columns as scoreboard_weekly>, coverage)` per spec §2.2; `run_id` ties each grade to the model version that served it.
* `grade_day(D)`: pull the served point forecast for D and realized `C` for D (SPP − system_λ); run `score_matrix(Y, Yh)` for each source available at serve time (model; persistence/climatology recomputed on D for context); write one row per source; snapshot the prediction-time inputs for miss-attribution. Schedule it one day behind `forecast_day`, after realized publishes.
* Miss-attribution (spec §4): decompose into **unforecastable-outage** (novel constraint bound with no history — from the Phase-2 novelty flag), **driver-forecast bust** (load/wind/solar forecast at DAM close vs realized), and **model error** (residual); persist alongside the daily grade.
* Endpoints: `GET /scoreboard/daily?since` and `GET /scoreboard/miss?date`; return baselines + oracle alongside model on every response (spec §3).
* Do NOT: redefine the gate or re-measure baselines outside the shared harness (spec §6); do NOT build the web panels here (0004); do NOT alter the backtest tables/endpoints (0001/0002).

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [ ] `scoreboard_daily` exists; `grade_day(D)` writes one row per source for a delivery day, with metrics + coverage keyed by `run_id`.
* [ ] Live grade reconciliation: `grade_day(D)` for an in-sample backtest D reproduces the backtest week's metric for D to tolerance (same `score_matrix`) (spec §7).
* [ ] Null guard: feeding the `null` source scores at chance, not inflated — the metric path still declines flat rows (spec §7).
* [ ] Each graded day stores a miss decomposition (unforecastable-outage / driver-forecast bust / model error) from prediction-time inputs.
* [ ] `GET /scoreboard/daily?since` returns per-delivery-day grades and `GET /scoreboard/miss?date` returns one day's decomposition, each carrying baselines + oracle alongside model.
