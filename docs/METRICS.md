# Product metrics

This document separates three independent product-metric surfaces:
**Scoreboard**, **Brief**, and **Map**. Their datasets, sources, targets, and
grades are specific to their own surface. A value from one section must not be
compared with, substituted for, or used to explain a value from another.

## Scoreboard

The served deterministic point forecast is `−(E[μ] · SF)`, where
`E[μ] = p_bind × mu_gbm`. Here, μ is a constraint shadow price and SF is the
constraint-to-node shift factor.

### At a glance

| Dataset | What it measures | Written by | How Scoreboard uses it |
| --- | --- | --- | --- |
| `scoreboard_weekly` | Offline walk-forward backtest | `compute.jobs.backfill_scoreboard` | Rolling headline, weekly track record, and lifetime splits |
| `scoreboard_daily` | Forecasts actually served and later settled | `compute.jobs.grade_forecast_day` | Latest final-grade tiles and final-grade portion of the history chart |

The only Scoreboard HTTP read endpoint is `/scoreboard/summary`. It bundles the
weekly backtest, its rolling headline, the latest final live grade, and the
combined history. The older `/scoreboard/headline`, `/scoreboard/weekly`, and
`/scoreboard/daily` routes no longer exist.

Each bundled section can be unavailable independently. A `null` section and its
`availability` entry mean its underlying data is not ready.

### Metrics

All Scoreboard metrics are higher-is-better and are computed on the same
realized nodal-congestion target: `SPP − system_λ`.

Think of metrics more as away of comparing orderings of forecast vs realized,
per hour (except for sign agreement which is pooled.)

| Metric                           | Meaning                                                                                                                      | Calculation Cadence      |
|----------------------------------|------------------------------------------------------------------------------------------------------------------------------|--------------------------|
| Rank ρ (`rank_spearman`)         | Mean hourly Spearman correlation between the predicted and realized ranking across settlement points.                        | average of hourly        |
| Top-Decile Hit (`topdecile_hit`) | Of the top 10% highest-congestion nodes, the mean hourly overlap between the predicted and realized.                         | average of hourly        |
| Sign Agreement (`sign_agree`)    | Fraction of node-hours whose predicted and realized signs (+ or -) match, among realized values outside the $1/MWh deadband. | pooled across entire day |

For a typical graded forecast

* Rank ρ: average of the valid hourly cross-node correlations - calculate
  spearman for all nodes per hour, then average those ~24 hours.
  * at time t, we order forecast nodes vs realized nodes by highest congestion,
    compare rank to get correlation..

* Top-Decile Hit: average of the valid hourly top-decile overlaps. Filter top
  decile each group, order for all nodes each hour, then average those ~24
  hours.
  * at time t, filter top 10% highest congestion, and rank to find overlap.

* Sign Agreement: not an average of 24 hourly scores. It pools all matching sign
  node-hour pairs (Forecast vs realized same direction) across the day, then
  calculates one overall fraction with matching signs.
  * match nodes, and test if +/- between forecast and realized was correct.

### Source catalog

The API identifies every scored construction with a canonical `SourceDescriptor`
`id`. Scoreboard points also carry a logical `series_id`; backtest and served
sources with the same `series_id` form one chart line. The model is always
interpreted alongside its other sources, rather than as a lone number:

| Canonical source ID | Series ID | Display label | Construction and status |
| --- | --- | --- | --- |
| `scoreboard_model_backtest_nodal` | `model` | Model Forecast | Offline deployable forecast construction. |
| `scoreboard_model_served_nodal` | `model` | Model Forecast | Forecast actually published for a delivery day; deployable. |
| `scoreboard_persistence_backtest_nodal` | `persistence` | Prior-day (Persistence) | Backtest baseline, using the fold’s map. |
| `scoreboard_persistence_prior_day_nodal` | `persistence` | Prior-day (Persistence) | Served-grade baseline, projected through the served forecast’s SF artifact. |
| `scoreboard_climatology_backtest_nodal` | `climatology` | Trailing-window Average (Baseline) | Backtest historical baseline. |
| `scoreboard_climatology_trailing_window_nodal` | `climatology` | Trailing-window Average (Baseline) | Served-grade historical baseline. |
| `scoreboard_oracle_backtest_nodal` | `oracle` | Settled-μ Benchmark (Oracle) | Non-deployable realized μ through the held-out fold map. |
| `scoreboard_oracle_settled_mu_nodal` | `oracle` | Settled-μ Benchmark (Oracle) | Non-deployable settled μ through the served forecast’s SF artifact. |
| `scoreboard_null_flat_nodal` | `null` | Flat nodal control | Non-deployable flat control; ranking metrics are usually undefined. |

For a live day, every source is scored on the same intersection of forecast,
map, and realized settlement points. Weekly folds hold their fold SF fixed for
every source; live grades hold the served artifact SF fixed for every source.
Both isolate μ-source differences within their own cadence. `sf_coverage`,
`n_hours`, and `n_nodes` travel with the rows as context for interpreting a score.

### Backtest and daily forecast (live) grades

#### Weekly backtest: does the recipe work?

`scoreboard_weekly` repeatedly fits only on information available at the time,
predicts forward, and scores the resulting out-of-sample forecasts.

`compute.jobs.backfill_scoreboard` persists weekly scores to `scoreboard_weekly`.
`compute.jobs.backfill_scoreboard` copies those precomputed screening values
into the database. The loader does not measure forecasts or create new metrics.

The backtest was a one-time catch-up to build a track record before daily
forecasts ran reliably; it is not maintained. Once daily grades are current they
take over past the last backtest week (see the pooled splits below).

#### Track record: pooled splits (All / Pre-RTC+B / Post-RTC+B)

The **Track record · pooled pre/post-RTC+B** panel shows one figure per source
for three spans, split at the 2025-12-05 RTC+B cutover:

* **Pre-RTC+B** — backtest weeks before the cutover.
* **Post-RTC+B** — backtest weeks on/after the cutover **plus** the live daily
  grades (all served days fall after it). This keeps advancing as the backtest
  ages out.
* **All weeks** — every period, backtest and live, across all time.

Each span is pooled on its own, weighting each period by its hours scored, so a
full backtest week (~168 hours) counts about seven times a served day (~24
hours). A span is not the average of the other two; "All weeks" spans the whole
history and is dominated by the long backtest record.

#### Daily served grade: did the published forecast hold up?

`scoreboard_daily` grades the nodal forecast that was actually served for a CT
delivery day after the corresponding DAM outcomes are available.

`compute.jobs.grade_forecast_day` reads the served forecast, builds realized
nodal congestion, and uses the same screening-metric harness as the backtest.

#### Same inference weekly vs daily, just different batch size

Both paths fit the μ heads (`P(bind)` and `E(μ | bind)`) from a trailing 240-day
history window, then run inference on timestamped constraint rows.

A model can infer one row or many rows at once - batching changes throughput,
not what a row means. Each row is identified by its full `interval_ts` and
constraint key, so Monday 14:00 and Tuesday 14:00 are distinct predictions even
though they share the same clock hour.

For a normal 24-hour delivery day `D`, `compute.jobs.daily_forecast` fits μ on
`[D−240d, D)`, reuses the applicable weekly-fit SF map, and infers the roughly
`24 × constraints` rows for `D`. It projects them to roughly `24 × nodes`
nodal predictions.

Once DAM results settle, `compute.jobs.grade_forecast_day` grades that day as
one daily Scoreboard result. (DST delivery days have 23 or 25 hours.)

For an offline weekly fold beginning `S`, the backtest fits both μ and SF on
the preceding 240 days, then infers the roughly `168 × constraints` rows for
`[S, S+7d)`. It projects them to roughly `168 × nodes` predictions and grades
all seven days together as one weekly result. The next fold advances seven days
and repeats with a newly shifted 240-day window.

### History boundary and overlapping dates

`/scoreboard/summary` returns `history.boundary_date`: the first final served
daily grade. The client passes it to `SeriesChart` in
`web/src/pages/ScoreboardPage.tsx`, which draws the dashed **Served grades**
marker at that date; it is a visual handoff, not a toggle or a server-side trim
of the weekly series.

If a weekly point and a daily point have the same date and source, the chart's
later daily value replaces the weekly value for plotting.

### Forecast horizons

Horizon is part of the forecast and daily-grade identity:

* **h1** is the final forecast, fired at 17:00Z on D−1 after DAM close.
* **h2** is the preview, fired at 20:15Z on D−2 before D's DAM auction clears.

Both tracks can be stored and graded independently in `scoreboard_daily`.

---

## Brief

Brief grades evaluate artifact-derived constraint and nodal-congestion profiles.
They are not nodal Scoreboard grades: a strong Brief grade does not imply a
strong Scoreboard result, and vice versa.

`topdecile_hit` is a Scoreboard-only metric. Brief Detection uses average
precision instead.

### Data and sources

| Dataset                | What it measures                   | Written by                             | Brief use         |
|------------------------|------------------------------------|----------------------------------------|-------------------|
| `analysis_grade_daily` | Brief ranking and shape assessment | `compute.jobs.materialize_brief_grade` | Brief grades only |

Brief profiles use their own source catalog because they score artifact profiles
rather than nodal Scoreboard rows:

| Canonical source ID                          | Display label                      | Status                             |
|----------------------------------------------|------------------------------------|------------------------------------|
| `brief_model_artifact_profile`               | Artifact profile forecast          | Deployable Brief forecast profile. |
| `brief_persistence_prior_settled_profile`    | Prior-settled profile persistence  | Brief baseline.                    |
| `brief_climatology_trailing_settled_profile` | Trailing-window Average (Baseline) | Brief baseline.                    |

The shared **Trailing-window Average (Baseline)** label describes a role, not
identical values:
* Brief averages prior settled constraint or node profiles directly.
* Scoreboard’s daily baseline averages trailing μ and projects it through the
  applicable map before scoring nodal congestion.

### Grades

These are explained in greater detail at
[/compute/analysis/README.md](/compute/analysis/README.md). Detection,
Magnitude, and Timing are shared concepts. They apply to constraint and node
grading, but use slightly different definitions because their settled signals
differ.

#### Constraints

Constraint grades use forecast and settled shadow-price profiles.

* **Detection**: Did the forecast put the constraints that bound near the top?
  Measured with average precision: constraints are ranked using the daily forecast
  shadow-price against constraints with a settled shadow-price.
* **Magnitude**: Did the forecast and settled summed shadow prices agree in
  amount and by constraint? Soft overlap calculates the shared price amount,
  divided by the average forecast and settled amount.
* **Timing**: Did the detected constraints appear in the correct delivery hours?
  The hourly value is average precision over constraint-hour cells, above and
  beyond "chance". The displayed daily value is daily Detection rescaled by
  the daily settled-event rate, not an additional timing test.

  Example: with 10 constraints and 2 settled events, a daily average precision
  of 0.60 becomes `(0.60 − 0.20) / (1 − 0.20) = 0.50` daily skill. With 20
  constraint-hour cells and 2 settled events, hourly average precision of 0.55
  becomes `(0.55 − 0.10) / (1 − 0.10) = 0.50` hourly skill.

#### Nodes

Node grades use absolute nodal congestion, `|SPP − system λ|`, projected from
the artifact and compared with settlement: they measure the size and location of
price separation, not whether a node was above or below system price.

* **Detection**: Did the forecast identify the nodes with the largest
  congestion? Nearly every node has some nonzero congestion, so a bind/no-bind
  label (which we use in constraint calculation) is not selective enough.
  Detection ranks all scored nodes by forecast total absolute congestion using
  average precision. The positive labels are the settled top 10% by total
  absolute congestion.
* **Magnitude**: Did forecast and settled absolute congestion agree in amount
  and by node? It is the same soft-overlap calculation as constraints, applied
  to absolute nodal congestion.
* **Timing**: Did the detected nodes appear in the correct delivery hours? The
  daily value is Detection rescaled by the selected-node rate, not an additional
  timing test. The hourly value selects the settled top 10% independently in
  each hour, calculates chance-adjusted average precision for each hour, then
  averages those skills.

  Example: for 20 nodes, the settled top 10% is 2 nodes. If their precision at
  forecast ranks is `1/1` and `2/4`, Detection is `(1.00 + 0.50) / 2 = 0.75`.
  Its selected-node rate is `0.10`, so daily Timing is
  `(0.75 − 0.10) / (1 − 0.10) = 0.72`.

These grades use their own subjects, baselines, and definitions.
`compute.jobs.materialize_brief_grade` writes them independently of
`compute.jobs.grade_forecast_day`.


---


## Map

Two SF-map fit-quality diagnostics surfaced in the `/map` sidebar. Both are
computed in `compute/evaluation/sf.py` and persisted to the `sf_window_meta`
table (columns `sf_oos_r2`, `sf_stability`); the API reads them back verbatim.

### SF OOS R2 (`sf_oos_r2`)

How well did the fitted shift factors reproduce congestion prices on data the
fit never saw.

Methodology:
* Fit the SF map on the 240-day window ending **strictly before** the scored
  week.
* Use ERCOT's **realized** constraint shadow prices (μ) with that fitted SF
  matrix to calculate *implied* congestion for the next 7 days:
  `C_hat = −M · SFᵀ`.
* Compare that implied congestion with **realized nodal congestion** for the
  same settlement-point-hours (DAM SPP minus ERCOT's system lambda).
* Score pooled across all settlement points x hours:
  `R² = 1 − Σ(y − ŷ)² / Σ(y − ȳ)²`.

The fit window does not touch the scored week (no leakage), and scoring uses
realized μ rather than forecast μ, so the number isolates the SF map's ability
to turn ERCOT shadow prices into realized congestion from any μ/bind-forecasting
skill. It is a reconstruction diagnostic, not a forecast score: `1` is a
perfect reconstruction, `0` is no better than predicting the scored week's
pooled average congestion, and a negative value is worse than that baseline.

This pooled level R² can move sharply in a single week. A newly or rarely
binding constraint may have no admitted SF row because it did not reach the
25-hour history threshold in the fit window; if it then carries a large share
of that week's shadow-price mass, its missing congestion footprint can dominate
the squared error. That is a map-coverage/regime-change warning, not evidence
that μ was forecast poorly.

The Scoreboard's settled-μ **Oracle** is related but reports rank correlation,
sign agreement, and top-decile hit rather than pooled R². When it uses the
same served causal SF artifact, it evaluates the same realized-μ projection
with different, pattern-oriented metrics.

### SF Stability (`sf_stability`)

Pearson correlation of the flattened SF matrix between two **adjacent,
non-overlapping** 240-day fit windows. How much of the map's structure survives
from one window to the next.

* `SF` is fit on `[s − 240d, s)`.
* `SF_older` is fit on `[s − 480d, s − 240d)` — touching at the edge, zero
  overlap.
* Correlate the two matrices over their shared constraint rows (requires ≥ 5).

Consecutive refits overlap 233/240 days (weekly fit), giving a flattering ≈ 0.90
that mostly measures shared training data.

The map can genuinely drift, so both numbers sit in the sidebar as a caveat on
the signed SF detail. `sf_stability` is NULL for early windows that lack the
480 days of history.

### Forecast Scorecard in the Map SidePanel

The Map SidePanel also has a **Forecast Run** section showing the μ-forecast
scorecard. It is not a rolling summary of the SF-map diagnostics, but a rehash
of the daily scoreboard metrics seen in `/scoreboard`. It prints the daily value,
so will change each day, but not hourly.

Each scorecard row compares the model forecast with persistence and the Oracle
settled-μ benchmark. All three metrics are higher-is-better and are calculated on the
predicted and realized nodal-congestion for each hour:


---


## Tracking Computation

These checks live under `/compute`. They are distinct from the `/map` sidebar:
the sidebar reads persisted `sf_window_meta` fields, while these are evaluation
commands and helpers used to assess a fitted map or a historical μ walk.

#### Scheduled μ forecast path: served to Brief.

The final and preview forecast CronJobs both run
`python -m compute.jobs.daily_forecast --to-db`; the final path uses horizon 1
and the preview path passes `--horizon 2`. `daily_forecast.forecast_day()`:

1. builds the delivery-day feature panel using only information available at
   that horizon's fire time;
2. calls `compute.mu_forecast.model.runner.predict_day()` to fit the two μ heads
   on the trailing training window and infer that one delivery day; and
3. loads the applicable persisted SF map, then calls `propagate_window()` to
   publish the deterministic nodal point forecast and its SF+μ artifact.

This path serves predictions; it cannot calculate forecast skill for the new
delivery day because settled DAM outcomes do not yet exist. On each tick it also
attempts a separate eligible settled-day Scoreboard grade through `grade_day()`
and `persist_grades()`, then materializes the separate Brief grade. Those are
settlement-time product grades, not training-time μ-head diagnostics.

* `grade_day()`: projects each `M` baseline (oracle, persistence, climatology,
  null) through the exact SF artifact served with that forecast, to get `Yh`.
  `/compute/evaluation/mu.py:screening_metrics_for_scoreboard(Y, Yh)`, a wrapper
  for `compute/metrics.py:screening_metrics(Y, Yh)` where the actual metrics for each baseline are
  calculated.


#### SF-map evaluation path — scheduled weekly - served to Map SidePanel

The production weekly SF `map-refresh` CronJob takes this branch, in order:

1. `compute.jobs.weekly_map` fits and persists each new rolling SF window.
2. `compute.sf_map.geography.persist` persists its geography overlay.
3. `python -m compute.evaluation.sf --persist-eval` evaluates the persisted
   map configuration and writes `sf_oos_r2`, `coverage`, and `sf_stability`
   back to matching `sf_window_meta` rows.

`compute.evaluation.sf.main()` For each scored week, `evaluate()`:

* fits the prior-window map with `implied_shift_factors()`;
* calls `predict()` with realized μ and scores `sf_pooled_r2()`,
  `row_spearman()`, `sign_agreement()`, and `topdecile_hit()` on the held-out
  nodal congestion panel;
* fits a comparison map whose window includes that week for in-sample R²; and
* fits the preceding, disjoint window and calls `_sf_corr()` for stability.

This is the SF gate: it holds μ at truth, so its results isolate map quality.

#### μ-forecast evaluation path - offline backtest (Scoreboard historic graph)

`compute.evaluation.mu` is an operator-run offline evaluation, not a map-refresh
CronJob branch. It consumes the prediction artifact from
`compute.mu_forecast.model.walk_forward` and uses `walk()` → `score_week()` for each
prediction week. The scoreboard job persists the resulting rows.

`score_week()` fits the same trailing-window SF map with
`implied_shift_factors()`, then passes each μ source through the shared
`compute.evaluation.sf.predict()` projection before applying the Scoreboard
screening helpers.

The sources are realized μ (oracle), the model’s `p_bind × mu_gbm`, trailing
hourly climatology, prior-day same-hour persistence, and a null (zero) control.

This path holds the map fixed within a week and compares μ inputs; it produces
rank Spearman, sign agreement, top-decile hit, SF coverage, and model-key
coverage.

#### μ-head diagnostics — backtest only (not used)

`compute.mu_forecast.model.walk_forward.walk_forward()` fits both heads on every
trailing training window and writes per-week head-1 diagnostics through
`compute.mu_forecast.model.heads.bind_metrics()` and `reliability()`: Brier
score, expected calibration error, AUC, base rate, and mean prediction. These
are not used anywhere except at one point internally.

There is currently no implemented head-2 R² gate in `/compute`.
