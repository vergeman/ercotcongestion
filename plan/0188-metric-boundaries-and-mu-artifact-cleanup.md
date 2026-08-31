# 0188 - metric-boundaries-and-mu-artifact-cleanup

Type: refactor
Branch: refactor/0188-metric-boundaries-and-mu-artifact-cleanup

## Goal

* Remove inactive μ severity-baseline outputs and shared magnitude metrics from serving and Scoreboard paths.
* Preserve legacy μ prediction artifact readability while writing the smaller active artifact shape.
* Keep map-quality and experiment-only diagnostics clearly scoped to their owners.

## Context

* `mu_clim` is calculated by every shared model fold, stored in `mu_preds.npz`, and dropped before serving; its MAE/R² comparison and `--extra-sources` diagnostic have no active consumer.
* Scoreboard stores only screening metrics, but its shared helper still calculates MAE and pooled R² before discarding them.
* `/map` actively presents Out-of-sample R² and SF Stability; these describe SF-map confidence, not a forecast grade.

## Approach

* Work in: `compute/mu_forecast/model/heads.py`, `runner.py`, `backtest.py`, `artifacts.py`, `compute/metrics.py`, `compute/experiments/mu/`, `compute/sf_map/`, `compute/jobs/weekly_map.py`, map API/client code, migrations, tests, and relevant docs.
* Remove `fit_mu_climatology`, `predict_mu_climatology`, `mu_clim`, `model_clim`, `--extra-sources`, μ-head MAE/R² columns and console verdicts. Make shared folds and `predict_day()` produce only `p_bind` and `mu_gbm`.
* Write new `mu_preds.npz` artifacts without `mu_clim`. Make `load_preds()` accept both the legacy array-rich artifact and the new artifact, returning the common active columns only.
* Replace the shared forecast `score_matrix` contract with a screening-only helper: rank Spearman, sign agreement, and top-decile hit. Remove shared `mae`, `pooled_r2`, and generic forecast `r2()` calculations.
* Keep MAE/R² only when an isolated experiment presents it as a final informational result. Compute and name it locally (for example, `experiment_mae` / `experiment_pooled_r2`); never return it through forecast artifacts, shared metrics, Scoreboard, Brief, or product APIs. Remove any calculation not presented by its owning experiment; do not comment it out.
* Preserve map diagnostics and make their ownership explicit: rename `fit_r2` / `r2_overall` to `sf_fit_r2`, `oos_r2` to `sf_oos_r2`, and retain `sf_stability`. Add lossless `sf_window_meta` column migrations and update persistence, API schemas, client types, logs, tests, SQL comments, and docs.
* Preserve `/map` labels **Out-of-sample R²** and **SF Stability** and their existing meanings. `sf_fit_r2` remains an internal fit diagnostic, while `sf_oos_r2` and `sf_stability` remain active map-confidence signals.

## Commit groups

1. `refactor(mu): remove inactive severity baseline` — slim folds/artifacts, retain legacy artifact reads, and remove μ-head reporting/tests.
2. `refactor(metrics): isolate screening and experiment metrics` — make production scoring screening-only and retain only explicit experiment-local summaries.
3. `refactor(map): namespace map confidence diagnostics` — migrate and rename SF diagnostic data/contracts without changing map-fit mathematics or `/map` labels.

## Acceptance

* [x] New μ artifacts omit `mu_clim`; `load_preds()` reads both artifact versions and serving/backfill use only active prediction values.
* [x] `mu_clim`, `model_clim`, `--extra-sources`, and μ-head MAE/R² are absent from active production outputs.
* [x] Scoreboard grading calculates only screening metrics; any MAE/R² exists solely as a named, final output of its owning experiment.
* [x] `sf_fit_r2`, `sf_oos_r2`, and `sf_stability` are preserved through migration, API, and client contracts; `/map` continues to show Out-of-sample R² and SF Stability.
* [x] Focused μ, artifact, Scoreboard-grade, SF persistence/API, and experiment tests pass.
