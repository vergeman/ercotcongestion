# implied_binding_proximity

Compute stage that fits implied shift factors from NP4-191-CD DAM shadow
prices against SPP congestion (`LMP − system_lambda`) on a rolling window,
then scores each hour with `bp_ercot[h, sp] = max_c |SF[c, sp]|` over the
constraints binding at that hour.

Method background: `docs/implied_binding_proximity.md`.

## Why `system_lambda` and not `zone_local_spp`

`--ref-method` is guarded to `system_lambda` (see `panels.py` and
`persist.py`), and it must stay that way. This trips people up because the
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

and *serves the absolute magnitude* `bp_ercot[h, sp] = max_c |SF[c, sp]|`. For
that output to mean what the map claims, the left-hand side must **be** the
true congestion component that `Σ SF·μ` is defined to equal. `system_lambda` is
already the correct additive reference in that identity, so `LMP −
system_lambda` is already pure congestion — the zone-mean of *that* quantity is
the average **real congestion** of the zone, not noise.

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
in the Trial-findings table were also calibrated against the `system_lambda`
target and would not transfer.) On the served map, `max_c |SF|` would then
answer *"how differently does this SP respond versus its zone-mates?"* — an SP
strongly but *uniformly* exposed to a binding constraint gets pulled toward
zero, the opposite of what a binding-proximity map wants.

| | Congestion-matrix correlation | Implied-SF fit (this stage) |
| --- | --- | --- |
| Operation | Pearson similarity | Regression to an additive identity |
| Cares about absolute level? | No (centered internally) | **Yes** — output is `max\|SF\|` |
| Zone mean is… | uninformative common-mode → strip it | **real congestion** → must keep it |
| De-meaning applied to… | both sides symmetrically | only the target → distorts coefficients |
| Correct ref | `zone_local_spp` | `system_lambda` |

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
* `--std-floor` — lower bound on the per-column shadow-price std used
  for standardization. Larger floors suppress `1/scale` inflation on
  low-variance columns (fewer SFs clip against the ±1 cap) at the cost
  of over-shrinking real signal from constraints that just happen to
  have small typical μ.

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
| `--min-binding-hours` | `25` | Drop constraints binding fewer hours in the window. |
| `--ridge-lambda` | `1e-1` | Ridge regularization strength on the standardized system. |
| `--std-floor` | `100.0` | Lower bound on per-column std used for standardization; see "Fit knobs". |
| `--ref-method` | `system_lambda` | Reference price for congestion. Only distributed-slack refs are compatible with this fit. |
| `--no-standardize` | (off) | Skip per-column standardization of `M`. |
| `--persist` | (off) | Write the panel to `implied_binding_proximity` under this `run_id`. Makes the run **available** in the DB. Does not change what the API serves. |
| `--promote` | (off) | Point `implied_binding_proximity_current[--layer]` at this `run_id`. Makes the run **served** by the API. Requires `--persist` (no-op otherwise). |
| `--layer` | `ercot` | Map layer `--promote` flips. |

### DB persistence

`bp_ercot.npz` is always the primary artifact. `--persist` writes the same
panel into Postgres (table `implied_binding_proximity`, keyed by `run_id`)
so the API can serve it without reading npz off disk. `--promote` flips the
`implied_binding_proximity_current` pointer in the same connection so
promotion is atomic with ingest.

Sweeps (`sweep_ibp.py`) leave both flags off — sweep panels stay on disk
where they can be inspected without polluting the served table. Once
you've calibrated and want to promote a fresh run, `runner.py --persist
--promote` does the fit and the DB update in one invocation.

To backfill an npz that's already on disk (e.g. an old run, or a sweep run
you've decided to promote after the fact), use
`compute.implied_binding_proximity.ingest` — it shares the same
`persist.py` helpers so the row shape is identical.

### Numerical guardrails

* `STD_FLOOR = 100.0` — default lower bound on per-column std used during
  standardization (overridable via `--std-floor`). Floors the scale so
  low-variance constraints don't get their coefficients inflated by the
  rescale-back step. See "Trial findings" for how this value was chosen.
* `SF_ABS_CAP = 1.0` — SFs are unitless in `[-1, 1]`; anything above is a
  numerical artifact and gets clipped. The clipped count is reported per
  refit as `n_sf_clipped`.

### Example

```bash
docker compose run --rm compute \
  python -m compute.implied_binding_proximity.runner \
    --run-id ibp_prod_2025 \
    --start 2025-01-01 --end 2026-01-01 \
    --persist --promote
```

Every knob defaults to the values in the "Trial findings" table below, so
this is the recommended production invocation. Drop `--persist --promote`
for exploratory single-run refits you don't want the API to serve.

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
| `--ridge-lambda` | `1e-2,1e-1,1` | Comma-separated grid; brackets the production default. |
| `--std-floor` | `50,100,200` | Comma-separated grid; brackets the production default. |
| `--min-binding-hours` | `10,25,50` | Comma-separated grid. Prunes rarely-binding constraints out of the fit before the ridge solve. |
| `--out` | *stdout* | If set, write the summary DataFrame to a CSV instead of printing. |

Each combination gets
`run_id = ibp_sweep_w{W}_r{R}_l{lam:g}_s{floor:g}_h{min_hours}`; that ID
is grep-able against the produced `runs/<run_id>/ibp/` directory.
The output table is sorted by `bp_max` descending so outliers surface at
the top.

### Example

```bash
docker compose run --rm compute \
  python -m compute.implied_binding_proximity.sweep_ibp \
    --start 2025-01-01 --end 2026-01-01 \
    --out /compute/implied_binding_proximity/ibp_sweep_summary.csv
```

The default grid is 2 × 3 × 3 × 3 = 54 combinations bracketing the
production defaults. A single combo over a full year takes ~4 minutes
inside the container; budget accordingly.

## Trial findings

The defaults above were picked from five trials against the 2025 DAM
shadow-price panel. All runs used `--window-days 60 --refit-days 7`;
`min_h` is `--min-binding-hours`, `floor` is `--std-floor`, `clipped` is
the total SF entries the ±1 cap caught across all refits. The raw
per-combo rows are in `ibp_sweep_trials.csv`.

| Trial | Range | min_h | floor | ridge λ | mean R² | median n_kept | p95 | p99 | clipped |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline           | 2025 H1 | 10 |   1 | 1e-1 | 0.983 | 683.5 | 1.000 | 1.00 | 260,270 |
| std-floor grid     | 2025 H1 | 10 |  25 | 1e-1 | 0.990 | 683.5 | 0.898 | 1.00 |   7,320 |
| floor + min_hours  | 2025 H1 | 25 |  50 | 1e-1 | 0.982 | 423.5 | 0.878 | 1.00 |   4,583 |
| floor + min_hours  | 2025 H1 | 25 | 100 | 1e-1 | 0.982 | 423.5 | 0.723 | 0.93 |   2,067 |
| window sweep (w=30)| 2025 H1 | 25 | 100 | 1e-1 | 0.975 | 267.5 | 0.558 | 0.89 |   1,334 |
| **full year**      | 2025    | 25 | 100 | 1e-1 | **0.985** | 422.5 | **0.559** | **0.895** | 2,538 |

The progression:

1. **Baseline** left the p95/p99/max all pinned at the cap of 1.0. The
   ±1 clip was catching 260k+ SF entries per run — evidence that the raw
   ridge solve was producing physically impossible values on a big chunk
   of low-variance constraints, not just a numerical tail.
2. **Raising `--std-floor` alone** (1 → 25) knocked ~35× off the clip
   count and dropped p95 off the cap, but p99 was still saturating.
3. **Stricter `--min-binding-hours`** (10 → 25) combined with `floor=100`
   pruned the noisy tail before the ridge saw it. First point where p99
   dropped below the cap (0.93). `min_h ≥ 50` cost too many constraints
   without further gains.
4. **Shorter windows** (30/45 vs 60) tightened the bulk further but shed
   ~40% of constraints — a tradeoff, not a strict win.
5. **Full-year run** improved every metric vs the 6-month version at the
   same settings: mean R² 0.982 → 0.985, p95 0.72 → 0.56, clip rate held
   at ~0.03% of cells over an 8730 × 1084 output. More history → more
   stable per-column scales → less inflation.

Net: the defaults now write into `fit.py` as `MIN_BINDING_HOURS = 25`,
`RIDGE_LAMBDA = 1e-1`, `STD_FLOOR = 100.0` reflect these findings.

### Corresponding sweep run

The calibrated combo lives on disk under
`compute/runs/ibp_sweep_w60_r7_l0.1_s100_h25/` — that's the sweep run_id
encoding the values in the "full year" row (window=60, refit=7, λ=1e-1,
std_floor=100, min_binding_hours=25). A plain `runner.py --run-id <name>`
with no knob overrides reproduces the same panel under `<name>` since
these are the module defaults. See
[`compute/runs/README.md`](../runs/README.md#sweep-run_id-naming) for the
full naming convention.

To persist this run to the API-served table:

```bash
docker compose run --rm compute \
  python -m compute.implied_binding_proximity.ingest \
    --run-id ibp_sweep_w60_r7_l0.1_s100_h25 --promote
```
