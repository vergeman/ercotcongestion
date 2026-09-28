# Implied Shift Factors (SF)

`sf_map/` contains the reusable map code; the scheduled CLI lives in
`compute/jobs/weekly_map.py`.

* `model/`: rolling windows, the ridge fit, optional constraint grouping, and
  fit diagnostics.
* `storage/`: writes and reads the weekly SF artifacts and metadata in Postgres.
* `geography/`: derives constraint geography from SF and persists the map
  overlay.
* `tests/`: checks for the fit, storage, geography, and input boundaries.

## Fit knobs

The five main knobs the runner and sweep share:

* `--window-days`: how much trailing history each fit sees. Longer
  windows smooth over week-to-week noise but blend across changes in the
  binding set; shorter windows track the current regime but see fewer
  binding hours per constraint.
* `--refit-days`: how often we re-solve. Shorter cadences keep SF
  current at the cost of more solves; `--refit-days 1` reproduces the
  prototype's daily refit, `7` matches the doc's weekly cadence.
* `--ridge-lambda`: L2 penalty on the standardized ridge solve. Larger
  λ trades bias for variance: shrinks noisy coefficients on rarely-
  binding constraints, at the cost of underfitting the well-conditioned
  bulk. Scaling makes the penalty more comparable across columns; the
  `--std-floor` below still gives quiet columns stronger effective shrinkage.
* `--std-floor`: lower bound on the per-column shadow-price std used
  for standardization. Larger floors suppress `1/scale` inflation on
  low-variance columns (fewer SFs clip against the ±1 cap) at the cost
  of over-shrinking real signal from constraints that just happen to
  have small typical μ.
* `--min-binding-hours`: minimum positive-shadow-price hours required
  for a constraint to enter the fit.

## Runner

The map runner (`python -m compute.jobs.weekly_map`) is the per-run CLI. It
reads the panels for the requested date range, walks the rolling window, and:

* writes `runs/<run_id>/sf/diagnostics_YYYYMMDD.json`; one file per refit
  boundary, with the fit's R² (overall and per-SP), kept/dropped constraint
  lists with binding-hour counts, and `n_sf_clipped` (SF entries the post-fit
  `[-1, 1]` cap caught);

* with `--persist-sf`, writes one dense float32 NPZ matrix to
  `sf_window_artifact` and one metadata row to `sf_window_meta`, keyed by
  `run_id`.

### Parameters

| Flag                  | Default         | Purpose                                                                                                   |
|-----------------------|-----------------|-----------------------------------------------------------------------------------------------------------|
| `--run-id`            | *required*      | Key in `sf_window_artifact` / `sf_window_meta`; also `runs/<run_id>/sf/` for diagnostics.                 |
| `--start`, `--end`    | *required*      | `[start, end)`; date-only, YYYY-MM-DD. `--start` is just the series origin.                               |
| `--window-days`       | `240`           | Trailing window used for each fit.                                                                        |
| `--refit-days`        | `7`             | Days between successive fits. `1` reproduces the prototype's daily refit.                                 |
| `--min-binding-hours` | `25`            | Drop constraints binding fewer hours in the window.                                                       |
| `--ridge-lambda`      | `1.0`           | Ridge regularization strength on the standardized system.                                                 |
| `--std-floor`         | `100.0`         | Lower bound on per-column std used for standardization; see "Fit knobs".                                  |
| `--ref-method`        | `system_lambda` | Reference price for congestion; only `system_lambda` is currently supported.                              |
| `--no-standardize`    | (off)           | Skip per-column standardization of `M`.                                                                   |
| `--persist-sf`        | (off)           | Write the full per-refit SF matrix as `sf_window_artifact` (+ `sf_window_meta`). Incremental by default.  |
| `--rebuild`           | (off)           | With `--persist-sf`, wipe all artifacts and metadata for this `run_id`, then refit every complete window. |
| `--chunk-weeks`       | `32`            | Required positive number of refit windows to load and fit per chunk.                                      |

### DB persistence (incremental append)

`--persist-sf` is the served path. By default it **appends**: a run fits and
writes only the refit boundaries it does not already have. `window_start` fully
determines a fit, so already-persisted boundaries are skipped (byte-identical to
recompute), and only **complete** windows — a full `refit_days` week on the
fixed grid — are persisted. The clamped terminal week is never written, so every
persisted `window_start` is immutable and the served map advances one complete
week per run. Re-running the same `--end` is a DB no-op.

`--rebuild` restores delete-then-rewrite: it wipes every artifact and metadata row for the
`run_id`, then refits and persists every complete window. The wipe shares the
fit loop's transaction (committed at the end), so a crash mid-rebuild leaves the
prior served windows intact.

The map API serves `max(window_start)`; there is no promote pointer. After a
persist run, `compute.sf_map.geography.persist` writes the constraint-geo overlay and
`compute.evaluation.sf` backfills the per-window OOS metrics onto `sf_window_meta`.
The weekly `ops/deploy/jobs/map_refresh_cronjob.yml` chains those three steps.

### Numerical guardrails

* `STD_FLOOR = 100.0`: default lower bound on per-column std used during
  standardization (overridable via `--std-floor`). Floors the scale so
  low-variance constraints don't get their coefficients inflated by the
  rescale-back step.
* `SF_ABS_CAP = 1.0`: SFs are unitless in `[-1, 1]`; anything above is a
  numerical artifact and gets clipped. The clipped count is reported per refit
  as `n_sf_clipped`.

### Example

```bash
docker compose run --rm compute \
  python -m compute.jobs.weekly_map \
    --run-id map-v1 \
    --start 2025-01-01 --end 2026-01-01 \
    --persist-sf
```

Every knob defaults to the adopted operating point (`config.py`), so this fits
at window 240 / refit 7 / λ 1.0 without passing them. Add `--rebuild` for a full
wipe + refit; drop `--persist-sf` for an exploratory diagnostics-only run.

## Sweep

`compute.experiments.sf.sweep` (`python -m compute.experiments.sf.sweep`)
orchestrates a grid over `(window-days, refit-days, ridge-lambda, std-floor,
min-binding-hours)`, fitting each combination in-process and ranking on the
honest out-of-window metrics from `compute.evaluation.sf` (default
`oos_pooled_r2`). Panels are loaded once and reused across combos. `--out` /
`--per-week-out` write the summary and per-week rows to CSV;
`compute.experiments.sf.grouping_verdict` scores a grouped-vs-ungrouped per-week
CSV stability bars. The sweep can also vary `--rho-min` for experimental
grouping; the weekly production runner uses ungrouped keys.
