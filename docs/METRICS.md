# Scoring

The product has two different grading systems. Scoreboard measures whether a
nodal congestion forecast screens the right locations and directions. The Brief
has its own artifact-based Detection, Magnitude, and Timing grades. They answer
different questions and must not be compared or substituted for one another.

The served deterministic point forecast is `−(E[μ] · SF)`, where
`E[μ] = p_bind × mu_gbm`. Here, μ is a constraint shadow price and SF is the
constraint-to-node shift factor.

## Scoreboard at a glance

Scoreboard is an all-hours, screening-only product surface. It has no net-load
quintiles or other regime selector, no magnitude mode, and no Scoreboard MAE or
R² metric.

| Dataset | What it measures | Written by | How Scoreboard uses it |
| --- | --- | --- | --- |
| `scoreboard_weekly` | Offline walk-forward backtest | `compute.jobs.backfill_scoreboard` | Rolling headline, weekly track record, and lifetime splits |
| `scoreboard_daily` | Forecasts actually served and later settled | `compute.jobs.grade_forecast_day` | Latest final-grade tiles and final-grade portion of the history chart |
| `analysis_grade_daily` | Brief ranking and shape assessment | `compute.jobs.materialize_brief_grade` | Brief only; not a Scoreboard input |

The only Scoreboard HTTP read endpoint is `/scoreboard/summary`. It bundles the
weekly backtest, its rolling headline, the latest final live grade, and the
combined history. The older `/scoreboard/headline`, `/scoreboard/weekly`, and
`/scoreboard/daily` routes no longer exist.

Each bundled section can be unavailable independently. A `null` section and its
`availability` entry mean its underlying data is not ready; they do not cause
the other Scoreboard sections to use a different run or substitute a preview
grade for a final grade.

## The three Scoreboard metrics

All Scoreboard metrics are higher-is-better and are computed on the same
realized nodal-congestion target: `SPP − system_λ`.

| Metric | Meaning |
| --- | --- |
| Rank ρ (`rank_spearman`) | Mean hourly Spearman correlation between the predicted and realized ranking across settlement points. |
| Sign Agreement (`sign_agree`) | Fraction of finite node-hours whose predicted and realized signs match, among realized values outside the $1/MWh deadband. |
| Top-Decile Hit (`topdecile_hit`) | Mean hourly overlap between the predicted and realized highest-congestion tenth of settlement points. |

The scorecard keeps only these screening metrics. MAE and pooled R² still exist
where independent model training, experiments, or SF diagnostics need them, but
they are not Scoreboard columns, API fields, controls, or verdicts.

## Source catalog

The API identifies every scored construction with a canonical `SourceDescriptor`
`id`. Scoreboard points also carry a logical `series_id`; backtest and served
sources with the same `series_id` form one chart line. The model is always
interpreted alongside its other sources, rather than as a lone number:

| Canonical source ID | Series ID | Display label | Construction and status |
| --- | --- | --- | --- |
| `scoreboard_model_backtest_nodal` | `model` | Model Forecast | Offline deployable forecast construction. |
| `scoreboard_model_served_nodal` | `model` | Model Forecast | Forecast actually published for a delivery day; deployable. |
| `scoreboard_persistence_backtest_nodal` | `persistence` | Prior-day (Persistence) | Backtest baseline, using the fold’s map. |
| `scoreboard_persistence_prior_day_nodal` | `persistence` | Prior-day (Persistence) | Served-grade baseline, using the trailing map. |
| `scoreboard_climatology_backtest_nodal` | `climatology` | Trailing-window Average (Baseline) | Backtest historical baseline. |
| `scoreboard_climatology_trailing_window_nodal` | `climatology` | Trailing-window Average (Baseline) | Served-grade historical baseline. |
| `scoreboard_oracle_backtest_nodal` | `oracle` | Settled-μ Ceiling (Oracle) | Non-deployable realized-μ ceiling. |
| `scoreboard_oracle_settled_mu_nodal` | `oracle` | Settled-μ Ceiling (Oracle) | Non-deployable settled-day ceiling. |
| `scoreboard_null_flat_nodal` | `null` | Flat nodal control | Non-deployable flat control; ranking metrics are usually undefined. |

Brief profiles use a separate source catalog because they score artifact
profiles rather than nodal Scoreboard rows:

| Canonical source ID | Display label | Status |
| --- | --- | --- |
| `brief_model_artifact_profile` | Artifact profile forecast | Deployable Brief forecast profile. |
| `brief_persistence_prior_settled_profile` | Prior-settled profile persistence | Brief baseline. |
| `brief_climatology_trailing_settled_profile` | Trailing-window Average (Baseline) | Brief baseline. |

The shared **Trailing-window Average (Baseline)** label describes the same
role, not identical values. Brief averages prior settled constraint or node
profiles directly. Scoreboard’s daily baseline averages trailing μ and projects
it through the applicable map before scoring nodal congestion. Do not compare
the values between those surfaces.

For a live day, every source is scored on the same intersection of forecast,
map, and realized settlement points. This makes model-versus-persistence
comparisons like-for-like. `sf_coverage`, `n_hours`, and `n_nodes` travel with
the rows as context for interpreting a score.

## Backtest and live grades

### Weekly backtest: does the recipe work?

`scoreboard_weekly` is a manually refreshed transcription of the offline
walk-forward evaluation. The walk repeatedly fits only on information available
at the time, predicts forward, and scores the resulting out-of-sample forecasts.
`compute.evaluation.mu` writes `mu_score_weekly.csv`;
`compute.jobs.backfill_scoreboard` copies those precomputed screening values
into the database. The loader does not measure forecasts or create new metrics.

There is one all-hours row per `(run_id, week, source)`. Refreshing the weekly
board requires a new offline walk, evaluation of its predictions, and then a
load; normal forecast and grading crons do not advance it.

### Daily served grade: did the published forecast hold up?

`scoreboard_daily` grades the deterministic nodal forecast that was actually
served for a CT delivery day after the corresponding DAM outcomes are available.
`compute.jobs.grade_forecast_day` reads the served forecast, builds realized
nodal congestion, and uses the same screening-metric harness as the backtest.
It records the model plus its comparators for the delivery day and is idempotent
for `(run_id, delivery_date, horizon)`.

The daily row is therefore a live product assessment, not another backtest. Its
history depends on forecasts having been served and later graded; it is not a
complete historical archive that can be rebuilt by the weekly-board loader.

### Same inference, different batch size

Both paths fit the μ heads (`P(bind)` and `E(μ | bind)`) from a trailing 240-day
history window, then run inference on timestamped constraint rows. A model can
infer one row or many rows at once; batching changes throughput, not what a row
means. Each row is identified by its full `interval_ts` and constraint key, so
Monday 14:00 and Tuesday 14:00 are distinct predictions even though they share
the same clock hour.

For a normal 24-hour delivery day `D`, `compute.jobs.daily_forecast` fits μ on
`[D−240d, D)`, reuses the applicable weekly-fit SF map, and infers the roughly
`24 × constraints` rows for `D`. It projects them to roughly `24 × nodes`
nodal predictions. Once DAM results settle,
`compute.jobs.grade_forecast_day` grades that day as one daily Scoreboard
result. (DST delivery days have 23 or 25 hours.)

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
value lookup is keyed by `(date, source)`. The API appends daily points after
weekly points, so the later daily value replaces the weekly value for plotting.
Thus daily takes precedence on an overlap, while non-overlapping weekly points
remain visible before and after the marker.

## Forecast horizons

Horizon is part of the forecast and daily-grade identity:

* **h1** is the final forecast, fired at 17:00Z on D−1 after DAM close.
* **h2** is the preview, fired at 20:15Z on D−2 before D's DAM auction clears.

Both tracks can be stored and graded independently in `scoreboard_daily` for
audit and other consumers. Scoreboard itself deliberately exposes only h1:
the live tiles select the newest fully persisted final delivery date and all of
its comparator rows. They never fall back to h2. The history chart likewise
appends final served daily grades only.

Earlier final daily grades are explored on that unified chart through hover or
keyboard navigation; the page has no delivery-date selector or horizon selector.

## Reading the Scoreboard page

| Page block | Data | Interpretation |
| --- | --- | --- |
| Live · latest final served grade | Newest h1 rows in `scoreboard_daily` | The most recent final forecast actually served, with model, persistence comparison, and oracle ceiling. |
| Backtest · rolling 90-day headline | `scoreboard_weekly` | Recent form of the offline walk. Each currency is pooled from weekly rows using `n_hours` weights. |
| Track record | Weekly backtest plus final daily grades | One continuous visual history with the two cadences kept distinct. |
| Backtest · pooled splits | `scoreboard_weekly` | All, pre-RTC+B, and post-RTC+B summaries; the split date is 2025-12-05. |

The metric buttons control the track-record chart and pooled-split table. They
do not change either row of headline tiles. The 90-day headline is calculated
when `/scoreboard/summary` is requested, so it changes only after new weekly
backtest rows are loaded.

The weekly pooled split values are simple means of the corresponding weekly
source values. `beats_persistence` is true only when the model is higher than
persistence on all three screening metrics.

## Delivery days and update flow

A delivery day is an America/Chicago trading day. It contains 23, 24, or 25
hours around DST transitions, while stored timestamps remain UTC instants.

The final and preview forecast ticks publish their artifacts and nodal forecasts,
then try to grade an eligible settled delivery day. Grade failures are non-fatal
to publishing and can be retried; `grade_forecast_day` selects an ungraded eligible day
per run and horizon. The offline weekly board is outside that loop.

Typical manual weekly refresh:

```bash
# Create walk-forward predictions, score them, then load the resulting CSV.
python -m compute.mu_forecast.model.backtest --run-id <run-id> ...
python -m compute.evaluation.mu --preds runs/<run-id>/mu/mu_preds.npz \
    --out runs/<run-id>/mu/mu_score_weekly.csv
python -m compute.jobs.backfill_scoreboard --run-id <run-id>
```

`backfill_scoreboard` replaces only that run's weekly rows. It does not backfill
daily served grades. To repair a specific live day, run
`python -m compute.jobs.grade_forecast_day --delivery-date <YYYY-MM-DD> --run-id
<run-id> --horizon <1|2> --to-db` after confirming the forecast and realized
inputs are present.

## Brief grades are separate

`analysis_grade_daily` evaluates artifact-derived constraint and node stories:

* Detection: whether the important constraints rank highly.
* Magnitude: whether the daily Σμ shape overlaps the realized shape.
* Timing: whether important constraint-hours appear at the right times.

Those grades use their own subjects, baselines, and definitions.
`compute.jobs.materialize_brief_grade` writes them independently of
`compute.jobs.grade_forecast_day`. A strong Brief grade does not imply a strong
nodal Scoreboard result, and vice versa.

## Metric families beyond product Scoreboard

Internal SF and μ gates deliberately keep their own executable metric tables so
one arena cannot silently change another. Their shared vocabulary is concise:

| Family | Metrics | Purpose |
| --- | --- | --- |
| SF gate | pooled R², rank Spearman, sign agreement, top-decile hit | Hold the μ input at truth and assess the SF map. |
| μ gate | pooled R², rank Spearman, sign agreement, top-decile hit | Hold the map fixed and assess μ forecasts. |
| Forecast internals | bind reliability, head-2 R² | Assess the two μ heads before projection. |
| Brief grade | detection, magnitude, timing | Assess served artifact profiles, separately for constraints and nodes. |

`oracle` always means a realized-input ceiling; `persistence` repeats the prior
settled same-hour signal; `climatology` is a trailing historical expectation;
and `null` is the flat control. Their exact subjects and information cutoffs are
defined by the named arena above, not shared across product surfaces.

## Migration appendix

The old short IDs `model`, `persistence`, `climatology`, `oracle`, and `null`
remain only as Scoreboard `series_id` values for joining logical chart lines.
They are not source identities and must not be used to select labels or explain
construction. Legacy API fields named `source`, `model`, `persistence`, and
`climatology` are retired; clients consume `source_id`, `series_id`,
`SourceDescriptor`, and source-metric entries instead.
