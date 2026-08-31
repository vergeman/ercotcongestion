# Evaluation

These programs check different parts of the congestion pipeline:

* `sf.py` checks the shift-factor (SF) map: given realized constraint pressure,
  how well does it reproduce nodal congestion?
* `mu.py` checks μ forecasts after they are passed through the SF map.
* `essp.py` compares the map's groups of similar points with ERCOT's ESSP list.

## `sf.py`: SF-map evaluation

`compute.evaluation.sf` fits an SF map using the history before each scored
week, then scores that next week with realized μ. This avoids evaluating a map
on data it was fit on.

Run it directly with:

```bash
python -m compute.evaluation.sf \
  --run-id map-v1 --start 2025-01-01 --end 2026-01-01 \
  --persist-eval
```

### Callers

* The production map-refresh CronJob runs this command after
  `compute.jobs.weekly_map` persists the map and
  `compute.sf_map.geography.persist` saves its geography overlay. With
  `--persist-eval`, it updates the map's stored evaluation fields.
* `compute.experiments.sf.sweep` calls `evaluate()` directly for every
  candidate configuration and uses the returned rows to rank the sweep.
* `compute.evaluation.mu` and `compute.jobs.grade_forecast_day` reuse the prediction or
  metric helpers in `sf.py`; they do not run the SF-map evaluation loop.
* `compute.sf_map.tests.test_grouped_fit` calls `evaluate()` and
  `evaluate_chunked()` to check grouping and chunked execution.

### Outputs

`evaluate()` and `evaluate_chunked()` return a pandas DataFrame with one row per
scored week. Its main columns are:

| Column                                         | Meaning                                                                            |
|------------------------------------------------|------------------------------------------------------------------------------------|
| `score_start`, `score_end`, `window_start`     | The scored period and the fit window that came before it.                          |
| `oos_pooled_r2`                                | Accuracy on the later, held-out week.                                              |
| `is_pooled_r2`                                 | Accuracy when the scored week is included in the fit window.                       |
| `rank_spearman`, `sign_agree`, `topdecile_hit` | Whether the map gets node ordering, direction, and the most congested nodes right. |
| `coverage`                                     | Share of scored-week μ mass represented by a fitted SF column.                     |
| `sf_stability`                                 | Similarity between SFs from adjacent non-overlapping fit windows.                  |
| `n_kept`, `n_constraints`                      | Fitted SF rows and constraints active in the fit window.                           |
| `n_groups`, `group_churn`, `sf_stability_proj` | Grouping-only fields; `sf_stability_proj` requires `--control`.                    |

The command writes:

* `compute/runs/<run-id>/sf/eval.csv` — the requested scored weeks.
* `compute/runs/<run-id>/sf/decay.csv` — only with `--emit-decay`; one row per
  requested lag (`delta_days`, `mean_corr`, `n_pairs`).
* `sf_window_meta` in Postgres — only with `--persist-eval`; it fills
  `oos_r2`, `coverage`, and `sf_stability` for matching map windows.

Useful options:

* `--rho-min` fits groups of closely related constraints instead of individual
  constraints.
* `--chunk-weeks` limits the amount of history kept in memory at once.
* `--emit-decay` measures how SF similarity changes as the time between fits
  grows.

## `mu.py`: μ-forecast evaluation

`mu.py` evaluates the μ model and simple alternatives using the same SF map.
It compares realized μ, the model forecast, a historical hourly average,
yesterday's same hour, and zero. Results are split before and after RTC+B so
the market change is visible.

## `essp.py`: ESSP cross-check

`essp.py` compares map groups with ERCOT's electrically similar settlement
point (ESSP) list. A group is compared only when all of its members appear in
both sources; missing data is not treated as either a match or a miss.
