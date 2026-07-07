# implied_binding_proximity

Compute stage that fits implied shift factors from NP4-191-CD DAM shadow
prices against SPP congestion (`LMP − system_lambda`) on a rolling window,
then scores each hour with `bp_ercot[h, sp] = max_c |SF[c, sp]|` over the
constraints binding at that hour.

Method background: `docs/implied_binding_proximity.md`.

## Fit knobs

The three knobs the runner and sweep share:

* `--window-days` — how much trailing history each fit sees. Longer
  windows smooth over week-to-week noise but blend across changes in the
  binding set; shorter windows track the current regime but see fewer
  binding hours per constraint.
* `--refit-days` — how often we re-solve. Shorter cadences keep SF
  current at the cost of more solves; `--refit-days 1` reproduces the
  prototype's daily refit, `7` matches the doc's weekly cadence.
* `--ridge-lambda` — L2 penalty on the standardized ridge solve. Larger
  λ trades bias for variance: shrinks noisy coefficients on rarely-
  binding constraints, at the cost of underfitting the well-conditioned
  bulk. Standardization means λ acts uniformly across columns regardless
  of their raw $/MWh scale.

## Runner

`runner.py` is the per-run CLI. It reads the panels for the requested date
range, walks the rolling window, and writes results under
`compute/runs/<run_id>/ibp/`:

* `bp_ercot.npz` — arrays `hours`, `settlement_points`, `bp_ercot`, `params`.
* `diagnostics_YYYYMMDD.json` — one file per refit boundary, with the fit's
  R² (overall and per-SP), kept/dropped constraint lists with binding-hour
  counts, and `n_sf_clipped` (number of SF entries the post-fit
  `[-1, 1]` cap caught).

### Parameters

| Flag | Default | Purpose |
| --- | --- | --- |
| `--run-id` | *required* | Output directory key (`runs/<run_id>/ibp/`). |
| `--start`, `--end` | from `reference_dates.json` | `[start, end)`; date-only, YYYY-MM-DD. |
| `--window-days` | `60` | Trailing window used for each fit. |
| `--refit-days` | `7` | Days between successive fits. `1` reproduces the prototype's daily refit. |
| `--min-binding-hours` | `10` | Drop constraints binding fewer hours in the window. |
| `--ridge-lambda` | `1e-2` | Ridge regularization strength on the standardized system. |
| `--ref-method` | `system_lambda` | Reference price for congestion. Only distributed-slack refs are compatible with this fit. |
| `--no-standardize` | (off) | Skip per-column standardization of `M`. |

### Numerical guardrails

* `STD_FLOOR = 1.0` — before dividing by column std, floor the scale so
  low-variance constraints don't get their coefficients inflated by the
  rescale-back step.
* `SF_ABS_CAP = 1.0` — SFs are unitless in `[-1, 1]`; anything above is a
  numerical artifact and gets clipped. The clipped count is reported per
  refit as `n_sf_clipped`.

### Example

```bash
docker compose run --rm compute \
  python -m compute.implied_binding_proximity.runner \
    --run-id ibp_prod_2025h1 \
    --start 2025-01-01 --end 2025-07-01 \
    --window-days 60 --refit-days 7 --ridge-lambda 1e-2
```

## Sweep

`sweep_ibp.py` orchestrates a grid over `(window-days, refit-days,
ridge-lambda)` by spawning the runner for each combination via
`subprocess.run`, then walks each run's `ibp/` directory to produce a
per-run summary row: `mean_r2`, `median_n_kept`, `bp_ercot`
p95/p99/max, and summed `n_sf_clipped`.

Panels are re-loaded per run (no reuse); each invocation is independent.

### Parameters

| Flag | Default | Purpose |
| --- | --- | --- |
| `--start`, `--end` | *required* | Passed through to every runner invocation. |
| `--window-days` | `60` | Comma-separated grid, e.g. `30,60,90`. |
| `--refit-days` | `7,14` | Comma-separated grid. |
| `--ridge-lambda` | `1e-3,1e-2,1e-1` | Comma-separated grid. |
| `--out` | *stdout* | If set, write the summary DataFrame to a CSV instead of printing. |

Each combination gets `run_id = ibp_sweep_w{W}_r{R}_l{lam:g}`; that ID is
grep-able against the produced `runs/<run_id>/ibp/` directory. The output
table is sorted by `bp_max` descending so outliers surface at the top.

### Example

```bash
docker compose run --rm compute \
  python -m compute.implied_binding_proximity.sweep_ibp \
    --start 2025-01-01 --end 2025-07-01 \
    --window-days 60 \
    --refit-days 7,14 \
    --ridge-lambda 1e-3,1e-2,1e-1 \
    --out /compute/implied_binding_proximity/ibp_sweep_summary.csv
```

The default 6-combo grid over a 6-month range takes roughly 30–60 minutes:
each combo re-queries Postgres for the full trailing window (~8 months
including warmup) and does a rolling fit across it.
