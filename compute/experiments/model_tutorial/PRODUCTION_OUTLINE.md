# SF and μ production outline

This is the companion to `walkthrough.py`.  The walkthrough intentionally
shows only the central equations; this document identifies the production
entry points, the data flow, and the responsibility of the surrounding files.

## The short version

The models are deliberately separate and connect only at projection time:

```text
DAM shadow prices M + SPP congestion C
        │
        ├─ weekly SF map ──> SF[constraint, settlement point]
        │                         │
DAM-close-safe inputs ─> daily μ heads ─> P(bind), E[μ | bind]
                                                  │
                                                  └─ samples × SF ─> nodal P10/P50/P90
```

* **SF** answers *where* a constraint's shadow price appears as congestion.
  It is a ridge regression fit weekly over a trailing 240-day window.
* **μ** answers *when and how strongly* each constraint will bind.  It is a
  pooled, daily-refit pair of gradient-boosted models: a binding-probability
  classifier and a conditional shadow-price regressor.
* Nodal congestion uses the signed identity
  `congestion[hour, SP] = -Σ(μ[hour, constraint] × SF[constraint, SP])`.
  The served bands sample binding and conditional μ, then take P10/P50/P90
  after that projection.

`M` is the wide DAM shadow-price panel (hours × constraints; zero when slack).
`C` is the wide congestion panel (hours × settlement points), calculated as
`LMP - system_lambda`.  The `system_lambda` reference is important: SF is a
structural regression on actual congestion, not the zone-relative correlation
mapping elsewhere in the project.

## Canonical package stages

Production code is now organized by the direction data moves: `compute.inputs`
owns shared DAM readers; `compute.sf_map` fits and stores the weekly map;
`compute.mu_forecast` builds daily features and predicts μ; `compute.projection`
turns μ and SF into nodal artifacts; and `compute.evaluation` scores them.
The former `compute.sf.*` and `compute.mu.*` paths have been removed; use these
stage packages for library imports and CLI commands.

## Production entry points and order

| When | Command/module | What it does | Main output |
| --- | --- | --- | --- |
| Weekly | `python -m compute.jobs.weekly_map` | Loads DAM M/C panels; fits each new rolling SF window; writes diagnostics and, with `--persist-sf`, the map. | `implied_shift_factors`, `sf_window_meta`, run diagnostics |
| Weekly, after map | `python -m compute.sf_map.geo_persist` | Derives and persists a map-based geographic overlay for constraints. | `constraint_geo` |
| Weekly, after map | `python -m compute.evaluation.sf` | Performs honest out-of-window SF evaluation and can persist metrics. | map evaluation fields / CSV |
| Daily | `python -m compute.jobs.daily_forecast` | Builds the DAM-close-safe μ panel for one delivery day, fits/predicts μ, loads a causal persisted SF map, samples and projects it, and optionally publishes. | nodal forecast + SF/μ artifact + current pointer |
| Historical rebuild | `python -m compute.mu_forecast.mu_model` | Runs the μ walk-forward backtest and saves per-row predictions/residuals. | `runs/<run-id>/mu/mu_preds.npz`, weekly μ metrics |
| Historical rebuild | `python -m compute.evaluation.mu` | Scores μ predictions against common baselines. | score CSV |
| Historical rebuild | `python -m compute.jobs.backfill_nodal` | Projects historical μ predictions through SF, makes nodal panels/bands, and evaluates the product gate. | nodal artifacts, band metrics |
| Historical rebuild | `python -m compute.jobs.backfill_artifacts` | Replays `daily_forecast` over dates to create served-style artifacts. | per-day DB artifacts |
| After delivery | `python -m compute.jobs.grade_day` | Grades what was actually served, including nodal and ESSP measures. | forecast grades |

The `compute/README.md` runbook contains the exact historical build sequence.
The key operational dependency is one-way: the daily forecast **loads** the
weekly persisted SF map; it does not refit SF.  A missing, stale, empty, or
low-coverage map makes the forecast fail before publication.

## SF: spatial map

### Fit path

1. `sf.panels.load_shadow_prices` reads `M`; `load_congestion_panel` reads
   `C` using `LMP - system_lambda`.
2. `sf.rolling.fit_refit_window` selects the trailing 240-day training window.
3. `sf.fit.implied_shift_factors` drops rarely binding constraints, standardizes
   shadow-price columns, ridge-solves `C = -M × SF.T`, rescales, and caps SF to
   `[-1, 1]`.
4. `jobs.weekly_map` emits diagnostics and persists complete weekly windows.
5. `sf.map_store.load_forecast_sf` selects the newest window ending no later
   than the delivery date and checks age and predicted μ-mass coverage.

### Files in `compute/sf`

| File | Responsibility | Production role |
| --- | --- | --- |
| `config.py` | Single source for the adopted window/refit/minimum-history/ridge operating point. | Shared by SF and μ schedules. |
| `panels.py` | Database reads, date bounds, and DAM coverage checks for M and C. | SF inputs; also reused by forecast/backfill jobs. |
| `fit.py` | The actual standardized ridge solver and SF cap. | Core SF model. |
| `rolling.py` | Rolling-window/refit scheduling and optional co-binding grouping before fitting. | Used by map runner and evaluation. |
| `diagnostics.py` | Per-refit R², kept/dropped constraints, clipping diagnostics. | Written by `weekly_map`. |
| `persist.py` | Postgres writes/reads for SF matrices, window metadata, and evaluation fields. | Map persistence. |
| `map_store.py` | Resolves and loads a causal map, plus freshness/coverage safety guards. | Used by `daily_forecast`. |
| `geo_persist.py` | Computes/persists constraint geographic summaries from each map window. | Post-map job. |
| `eval.py` | Honest out-of-window SF metrics, chunking, decay/stability measures, and CLI. | Post-map evaluation and sweep backend. |
| `project.py` | Turns μ predictions/draws into nodal panels and SF+μ artifacts. | Shared by daily forecast and historical nodal backfill. |
| `sampling.py` | Residual-pool construction, Monte Carlo draw logic, percentiles, band metrics. | Used by `project.py`. |
| `codecs.py` | Compact NPZ-like artifact encodings, node drivers, and artifact reads. | Used by projection, APIs, and jobs. |
| `essp.py` | Independent validation against final ERCOT ESSP labels. | Used by served-forecast grading. |
| `grouping.py` | Identifies co-binding/collinear constraints and can aggregate/project group maps. | An experimental option to the SF fit, not the default map path. |

### Is there SF ablation code?

Yes, but it is model-selection/diagnostic work rather than the ordinary weekly
map job.

* `experiments/sf/sweep.py` varies the SF hyperparameters and ranks candidates
  on the out-of-window measures from `sf.eval`.
* `experiments/sf/grouping_verdict.py` evaluates whether the optional
  co-binding grouping in `sf.grouping` improves stability enough to justify it.
* `experiments/sf/coverage.py` explains coverage gaps and admission history.
* `experiments/sf_out_of_window/` is a self-contained historical study:
  `oos_gate.py`, `screening_and_coverage.py`, and `sf_stability.py` share
  `common.py` and write the checked-in result CSVs.

None of these are called by the map-refresh cron job.  In particular,
`rho_min=None` leaves grouping off in the default rolling fit.

## μ: per-constraint shadow-price forecast

### Fit and serving path

1. `sf.panels` reads trailing `M` (and `C` when a geography/outage arm needs
   an honestly fitted SF).
2. `mu.features.build_panel` constructs one long row per `(delivery hour,
   candidate constraint)`.  It joins DAM-close-vintaged load/wind/solar/outage
   inputs, calendar values, and backward-only constraint history.  Day D's
   shadow price exists only in `y_bind`/`y_mu`, never in features.
3. `mu.mu_model.predict_day` uses the same fold implementation as the
   walk-forward validation: pooled classifier for `p_bind`, and a regressor fit
   only on binding rows for conditional `mu_gbm` / `E[μ | bind]`.
4. `jobs.daily_forecast.forecast_day` loads a causal SF map, builds a residual
   pool from **prior out-of-sample** μ errors, and calls `sf.project` to sample
   and project nodal congestion.
5. The deterministic expectation is `p_bind × mu_gbm`; uncertainty uses a
   Bernoulli binding draw plus log-space residual draw for μ.  The code currently
   samples constraints independently, so coverage evaluation is important for
   correlated constraints.

### Files in `compute/mu`

| File | Responsibility | Production role |
| --- | --- | --- |
| `availability.py` | DAM-close timestamp, history cutoff, CT delivery-day bounds, SQL vintage predicates. | The time/leakage boundary. |
| `panel_sources.py` | Database readers for vintaged load, wind, solar, and zonal outage inputs. | Inputs to feature panel. |
| `panel_engineering.py` | Pure calendar/history/regime/candidate-key engineering and leakage audit. | Feature primitives. |
| `features.py` | Assembles the long μ panel, targets, and optional feature arms. | Main feature entry point. |
| `heads.py` | Target encoding; gradient-boosted classifier/regressor fitting and predictions; μ climatology baseline. | Two-head primitives. |
| `scheduling.py` | Calendar-safe refit boundaries and chunks. | Shared walk scheduling. |
| `mu_model.py` | Feature-set selection, common fold routine, walk-forward runner, one-day prediction, CLI/artifact paths. | Core μ model and historical entry point. |
| `artifacts.py` | Serializes/deserializes μ per-row prediction artifacts and combines chunks. | Backtest-to-projection handoff. |
| `score.py` | Shared historical scoring harness and persistence/climatology/oracle baselines. | Evaluation, not live fitting. |
| `geo.py` | Builds causal constraint-location features from |SF|-weighted settlement-point geography. | Optional `geo_` arm. |
| `weather.py` | Builds causal, per-constraint weather-response vectors. | Optional `wx_` arm. |
| `outage/crosswalk.py` | Loads/covers the authoritative resource-unit → settlement-point crosswalk. | Supports outage exposure. |
| `outage/exposure.py` | Builds causal, per-constraint `|SF| × located outage MW` features using an admissible D-1 snapshot and planned end dates. | Optional `out_` arm. |

### What the outage code is doing

There are two outage levels in the feature panel:

* The base panel contains **zonal** outage aggregates, the same value for every
  constraint in an hour.
* The optional `out_` arm attempts the more useful constraint-specific signal:
  locate unit outages to settlement points through the NP1-346 crosswalk, then
  calculate `Σ_sp |SF[constraint, sp]| × outage_MW[sp]`.

The latter is deliberately causal: its SF is refit only on preceding history,
and it selects the latest outage snapshot posted no later than D-1.  It also
has a planned-outage variant that retains units expected to remain out on D.

`out` and `all+out` are available `--features` choices, but the standard
`all` set is `lag + geo + wx` and excludes outage exposure.  That makes the
outage files production-capable feature plumbing, while their incremental value
is assessed separately by `experiments/mu/outage_ablation.py`.

### μ experiments and ablations

* `experiments/mu/feature_ablation.py` compares `base`, `lag`, `geo`, `wx`, and
  `all` on one identically built panel; each arm is a column mask, not a separate
  data build.
* `experiments/mu/outage_ablation.py` compares `base`, `all`, `out`, and
  `all+out`; its meaningful comparison is against the already-present zonal
  outage signal in `base`.
* `experiments/mu/rerank.py` is a post-hoc ranking analysis of draws; it does
  not change the production model.

## `experiments/` versus `probes/`

Neither directory is part of forecast serving or called by the production
cron jobs.  They answer different questions:

* **`experiments/`** asks *does a model configuration or feature improve an
  existing, reproducible historical harness?* It uses the project panels and
  metrics, writes local CSV/NPZ results, and is where a configuration earns a
  promotion into `sf/` or `mu/`.
* **`probes/`** asks *is a proposed external input even available, timely, and
  joinable enough to justify ingest/model work?* They are read-only discovery
  and feasibility scripts. They may read the database and ERCOT public API, but
  do not ingest data, write the DB, or serve a forecast.

### `compute/experiments/sf`

| File | Question it answers |
| --- | --- |
| `sweep.py` | Which `(window, refit cadence, ridge λ, std floor, admission threshold, optional grouping)` configuration performs best out of sample? It uses `sf.eval` rather than in-sample fit quality. |
| `grouping_verdict.py` | Does grouping collinear/co-binding constraints materially improve refit stability without damaging OOS accuracy/locality? It consumes the sweep's per-week CSV. |
| `coverage.py` | What part of predicted μ mass is missing from the current SF map, and how much could a historical warm-start library realistically recover? |

### `compute/experiments/mu`

| File | Question it answers |
| --- | --- |
| `feature_ablation.py` | Which of the base, lag, geography, weather-response, and combined feature arms helps? It holds the panel, weeks, SF operating point, and scoring harness fixed. |
| `outage_ablation.py` | Does the per-constraint outage-exposure arm add value beyond the base panel's zonal outage aggregates, alone or on top of all other arms? |
| `rerank.py` | If expected congestion misses tail/ranking measures, does ranking the *same sampled distribution* by an upper quantile help? It is post-hoc analysis, not a refit or promotion path. |

### `compute/experiments/sf_out_of_window`

This is an older, fixed-window SF study with checked-in result CSVs, useful for
reproducing historical claims rather than running the production map:

| File | Role |
| --- | --- |
| `common.py` | Shared panel loading, fit window, baseline μ forecasts, and metrics. |
| `oos_gate.py` | Tests whether SF has useful out-of-window value versus its ceiling/baselines. |
| `screening_and_coverage.py` | Measures rank/sign/top-decile screening and coverage questions the pooled R² gate misses. |
| `sf_stability.py` | Compares overlapping versus disjoint fit windows to measure real SF drift rather than overlap-induced correlation. |

### `compute/probes`

| File | External-data feasibility question |
| --- | --- |
| `ruc.py` | Can public RUC enforced-constraint data cover the backtest, arrive by DAM close for the delivery day, match the DAM constraint namespace, and have useful cadence? |
| `outage_join.py` | Can constraint station identities be joined to a reachable *named transmission-outage* feed? It documents that the needed feed is not currently reachable, distinguishing station resolution from actual joinable μ mass. |
| `outage_feed.py` | Can ERCOT NP1-346 unit-level generation outages support a per-constraint feature? It probes archive depth, DAM-close vintage timing, MW-weighted unit→SP join coverage, and incremental signal over zonal outages. |
| `outage_crosswalk.py` | A focused Gate-C recheck: samples NP1-346 snapshots and reports MW-weighted coverage through the maintained unit/substation→settlement-point crosswalk. |
| `__init__.py` | Marks this package as external-data feasibility work, not forecast serving. |

The distinction matters for outage work: `outage_feed.py` and
`outage_crosswalk.py` decide whether the data source and crosswalk clear their
gates; `mu/outage/*.py` is the feature implementation that can be run once they
do; `experiments/mu/outage_ablation.py` measures whether the resulting feature
actually improves the model.

## Useful reading order

For the shortest realistic code tour, read these in order:

1. `walkthrough.py` and this document for the equations and vocabulary.
2. `jobs/daily_forecast.py:forecast_day` for the served end-to-end path.
3. `mu/features.py:build_panel`, then `mu/mu_model.py:predict_day` and
   `_predict_fold`, for the μ inputs and two heads.
4. `sf/map_store.py:load_forecast_sf` and `sf/project.py:propagate_window`, for
   the model handoff and uncertainty bands.
5. `jobs/weekly_map.py`, `sf/rolling.py`, and `sf/fit.py`, for how SF is built.
6. `experiments/*` only when examining a particular design decision or ablation.
