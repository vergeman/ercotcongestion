# Implied shift factors (SF)

Compute stage that fits implied shift factors from NP4-191-CD DAM shadow
prices against SPP congestion (`LMP − system_lambda`) on a rolling window,
refit every `--refit-days`. Each refit's `SF` matrix (constraint × settlement
point) and a per-refit metadata row are persisted to Postgres, where the v3
explorer map reads them. The served window is always `max(window_start)`.

The adopted operating point (window 240d, refit 7d, ridge-λ 1.0, min-binding-
hours 25, std-floor 100) lives in `config.py` / `model/fit.py` and is shared with the
μ forecast (`compute.mu_forecast`) so the two pipelines fit at the same point; see
`plan/0082-oos-eval-and-resweep.md` for the sweep that selected it.

Method background: `docs/legacy/implied_binding_proximity.md`.

## Why `system_lambda` and not `zone_local_spp`

`--ref-method` is guarded to `system_lambda` (see `compute.inputs.dam` and
`storage/persist.py`), and it must stay that way. This trips people up because the
**congestion-matrix correlation** stage (`compute.mapping.correlation_map`)
deliberately uses `zone_local_spp` — a sweep there showed that de-meaning
zonal common-mode captured the real congestion structure better. That result
is correct *there* and does **not** transfer here, because the two stages do
fundamentally different math.

**Correlation is a similarity measure.** `correlation_map` scores each
model-bus / SP pair with Pearson correlation, which internally centers each
series by its own mean and is invariant to any affine shift. It asks "does SP
`j` *move like* bus `i`?" For that question, stripping the zonal common-mode is
a legitimate normalization: the removed component is uninformative for
discriminating which bus an SP maps to, and it is applied symmetrically to both
sides of a measure that ignores absolute level. Hence the sweep win.

**The implied-SF fit is a structural regression, not a similarity.** It
reconstructs the ERCOT LMP decomposition identity

```
LMP[sp] − system_lambda = Σ_c SF[c, sp] · μ_c          (− losses)
```

and the map *serves the absolute magnitude* `max_c |SF[c, sp]|` (per-constraint
`max_abs_sf`, per-node `node_max_abs_sf`). For that output to mean what the map
claims, the left-hand side must **be** the true congestion component that
`Σ SF·μ` is defined to equal. `system_lambda` is already the correct additive
reference in that identity, so `LMP − system_lambda` is already pure congestion
— the zone-mean of *that* quantity is the average **real congestion** of the
zone, not noise.

De-meaning by zone therefore corrupts the fit in a way it cannot corrupt the
correlation:

```
LMP[sp] − zone_mean = Σ_c ( SF[c, sp] − ⟨SF[c, ·]⟩_zone ) · μ_c
```

You would recover **zone-relative** shift factors, not physical ones. And
unlike correlation you can only de-mean one side — the features `μ_c` are
system-constraint shadow prices, not zonal quantities — so the ridge is forced
to explain a de-meaned target with non-de-meaned features and absorbs the
discrepancy into distorted coefficients. (The `[-1, 1]` SF cap and `std_floor`
were also calibrated against the `system_lambda` target and would not transfer.)
On the served map, `max_c |SF|` would then answer *"how differently does this SP
respond versus its zone-mates?"* — an SP strongly but *uniformly* exposed to a
binding constraint gets pulled toward zero, the opposite of what the SF map
wants.

| | Congestion-matrix correlation | Implied-SF fit (this stage) |
| --- | --- | --- |
| Operation | Pearson similarity | Regression to an additive identity |
| Cares about absolute level? | No (centered internally) | **Yes** — output is `max\|SF\|` |
| Zone mean is… | uninformative common-mode → strip it | **real congestion** → must keep it |
| De-meaning applied to… | both sides symmetrically | only the target → distorts coefficients |
| Correct ref | `zone_local_spp` | `system_lambda` |

## Fit knobs

The four knobs the runner and sweep share:

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
* `--std-floor` — lower bound on the per-column shadow-price std used
  for standardization. Larger floors suppress `1/scale` inflation on
  low-variance columns (fewer SFs clip against the ±1 cap) at the cost
  of over-shrinking real signal from constraints that just happen to
  have small typical μ.

## Runner

The map runner (`python -m compute.jobs.weekly_map`) is the per-run CLI. It reads the
panels for the requested date range, walks the rolling window, and:

* writes `runs/<run_id>/sf/diagnostics_YYYYMMDD.json` — one file per refit
  boundary, with the fit's R² (overall and per-SP), kept/dropped constraint
  lists with binding-hour counts, and `n_sf_clipped` (SF entries the post-fit
  `[-1, 1]` cap caught);
* with `--persist-sf`, writes each refit's `SF` matrix to
  `implied_shift_factors` and one metadata row to `sf_window_meta`, keyed by
  `run_id`.

### Parameters

| Flag | Default | Purpose |
| --- | --- | --- |
| `--run-id` | *required* | Row key in `implied_shift_factors` / `sf_window_meta`; also `runs/<run_id>/sf/` for diagnostics. |
| `--start`, `--end` | *required* | `[start, end)`; date-only, YYYY-MM-DD. `--start` is just the series origin. |
| `--window-days` | `240` | Trailing window used for each fit. |
| `--refit-days` | `7` | Days between successive fits. `1` reproduces the prototype's daily refit. |
| `--min-binding-hours` | `25` | Drop constraints binding fewer hours in the window. |
| `--ridge-lambda` | `1.0` | Ridge regularization strength on the standardized system. |
| `--std-floor` | `100.0` | Lower bound on per-column std used for standardization; see "Fit knobs". |
| `--ref-method` | `system_lambda` | Reference price for congestion. Only distributed-slack refs are compatible with this fit. |
| `--no-standardize` | (off) | Skip per-column standardization of `M`. |
| `--persist-sf` | (off) | Write the per-refit SF matrix to `implied_shift_factors` (+ `sf_window_meta`). Incremental by default. |
| `--rebuild` | (off) | With `--persist-sf`, wipe all rows for this `run_id` first, then refit + persist every complete window from scratch. |
| `--sf-threshold` | `1e-3` | With `--persist-sf`, drop SF entries with `\|sf\| <` this. The matrix is dense but mostly negligible; keeps row counts sane. |
| `--chunk-weeks` | `32` | Required positive number of refit windows to load and fit per chunk. |

### DB persistence (incremental append)

`--persist-sf` is the served path. By default it **appends**: a run fits and
writes only the refit boundaries it does not already have. `window_start` fully
determines a fit, so already-persisted boundaries are skipped (byte-identical to
recompute), and only **complete** windows — a full `refit_days` week on the
fixed grid — are persisted. The clamped terminal week is never written, so every
persisted `window_start` is immutable and the served map advances one complete
week per run. Re-running the same `--end` is a DB no-op.

`--rebuild` restores the old delete-then-rewrite: it wipes every row for the
`run_id`, then refits and persists every complete window. The wipe shares the
fit loop's transaction (committed at the end), so a crash mid-rebuild leaves the
prior served windows intact.

The map API serves `max(window_start)`; there is no promote pointer. After a
persist run, `compute.sf_map.geography.persist` writes the constraint-geo overlay and
`compute.evaluation.sf` backfills the per-window OOS metrics onto `sf_window_meta`.
The weekly `ops/deploy/jobs/map_refresh_cronjob.yml` chains those three steps.

### Numerical guardrails

* `STD_FLOOR = 100.0` — default lower bound on per-column std used during
  standardization (overridable via `--std-floor`). Floors the scale so
  low-variance constraints don't get their coefficients inflated by the
  rescale-back step.
* `SF_ABS_CAP = 1.0` — SFs are unitless in `[-1, 1]`; anything above is a
  numerical artifact and gets clipped. The clipped count is reported per
  refit as `n_sf_clipped`.

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
CSV against the plan/0083 stability bars.
