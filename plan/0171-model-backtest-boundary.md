# 0171 - model backtest boundary

Type: refactor
Branch: refactor/0171-model-backtest-boundary

## Goal

* Move historical walk-forward orchestration and its CLI out of `model.runner` into a dedicated backtest module.
* Retain one shared fold-prediction implementation for historical walks and `predict_day` serving.
* Preserve walk artifacts, metrics, daily forecasts, and causal/key-eligibility behavior.

## Context

* `runner.py` currently combines shared fold mechanics, one-day inference, long-history backtesting, chunked memory management, artifact I/O, and a historical-run CLI.
* `walk_forward_chunked` is only a bounded-memory wrapper around repeated `walk_forward` calls; it is not part of the daily serving path.
* `predict_day` shares `_predict_fold` with walks but has deliberate CT-day and novel-key handling; `forecast_day` additionally owns SF projection and publishing.

## Approach

* Work in: `compute/mu_forecast/model/runner.py`, new `compute/mu_forecast/model/backtest.py`, callers, tests, and command documentation.
* Entry point / primary change: move `walk_forward`, `walk_forward_chunked`, chunk helpers, and the historical-run `main()` CLI into `model.backtest`.
* Keep shared modeling/fold primitives, `predict_day`, feature selection, spill helpers, and prediction artifact read/write helpers in `runner.py`; make the shared fold interface explicit enough for `backtest.py` to import without circular dependencies.
* Update offline callers (`feature_ablation`, `outage_ablation`, tests, and documentation) to import/run `model.backtest`; retain a small compatibility entry point only if existing operational commands require it.
* Preserve `forecast_day → predict_day → shared fold` as the serving path. Do not route daily forecasts through chunked walks or mix SF propagation/persistence into the backtest module.
* Add/retain regression coverage that: a chunked walk equals a whole-panel walk; `predict_day` agrees with the corresponding one-day walk where their eligibility policies overlap; daily novelty accounting remains unchanged.
* Do NOT change: training windows, refit-grid phase, target definitions, feature arms, model hyperparameters, output formats, or published run IDs.

## Acceptance

* [x] `python -m compute.mu_forecast.model.backtest` performs the existing historical walk, including default chunked execution and the same output artifacts/metrics.
* [x] Daily forecast and artifact-backfill paths still import `predict_day`/shared primitives from `runner` and do not import historical-walk orchestration.
* [x] Direct and chunked walks remain prediction- and metric-equivalent, and existing daily-vs-walk reconciliation and novelty tests pass.
* [x] Repository callers and docs reference the new backtest module; any compatibility path is documented and tested.
