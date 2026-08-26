# A small walkthrough: SF and μ

This is a runnable, synthetic example of the two models. It leaves out the
database, long training windows, refit schedule, and production feature list so
the main calculation is easy to see.

Run it from the repository root:

```bash
python -m compute.experiments.model_tutorial.walkthrough
```

The numbers are made up. The input and output shapes, signs, and two-head
calculation follow the production code in `compute.sf_map.model.fit` and
`compute.mu_forecast.model.heads`.

## 1. The inputs

Every row is one delivery hour.

`M` is a wide table of DAM constraint shadow prices. Its rows are hours and its
columns are constraints. A zero means that constraint did not bind.

| hour | north_line | west_line | coast_line |
| --- | ---: | ---: | ---: |
| 14:00 | 42 | 0 | 10 |
| 15:00 | 67 | 18 | 26 |

`C` is a second wide table over the same hours. It is congestion at each
settlement point:

```text
C[hour, point] = LMP[hour, point] - system_lambda[hour]
```

The tutorial also makes a long table for the μ forecast. It has one row per
`(hour, constraint)`. Its small set of inputs is `net_load`, `hour`, and a
training-only historical binding rate for that constraint. Production adds more
safe-at-DAM-close inputs, such as forecast load, wind, solar, outage, and
history features.

## 2. Ridge regression makes the SF map

For each settlement point, we fit this relationship across the training hours:

```text
congestion = - (shadow price 1 × SF 1
                + shadow price 2 × SF 2
                + ...)
```

In matrix form, that is:

```text
C = -M × SF.T
```

Ridge regression is ordinary fitting with a small preference for modest
coefficients. That keeps the map from overreacting when constraints move
together or one has little history. Before fitting, the production code scales
each shadow-price column so the penalty treats columns fairly, then converts the
answers back to their normal scale.

The result is `SF`, a table with constraints as rows and settlement points as
columns. A value says how much that constraint's shadow price contributes to
congestion at that point. The minus sign above is intentional and matches the
ERCOT LMP decomposition used by the code.

The tutorial calls the actual `implied_shift_factors` helper, with a much smaller
minimum-history rule than production. In production, the fit is retrained weekly
using a trailing 240-day window and ignores constraints that bound too rarely.

## 3. Two heads make the μ forecast

For every future `(hour, constraint)` row, the model answers two different
questions.

1. **Will it bind?** The first head returns `p_bind`, a number from 0 to 1.
2. **If it binds, how large will its shadow price be?** The second head returns
   `mu_if_bind` in $/MWh.

The first head trains on every training row and uses `y_bind` (0 or 1). The
second head trains only on rows where `y_bind` is 1. Leaving zero rows out is
important: it makes its answer conditional on a bind, instead of averaging in
all the hours with no shadow price.

The two answers combine as:

```text
expected_mu = p_bind × mu_if_bind
```

For example, `p_bind = 0.25` and `mu_if_bind = $80/MWh` gives an expected shadow
price of `$20/MWh` before any uncertainty sampling.

The real μ model uses gradient-boosted trees for both heads. For the size head,
it fits `log(1 + μ)` and converts the prediction back afterwards; that stops a
few unusually large prices from dominating the fit. The tutorial uses those same
small model helpers.

## 4. How they connect

The two models play different roles:

```text
future inputs → P(bind), E[μ | bind] → expected μ
                                       │
                                       ▼
                              SF map → expected congestion at each point
```

For one point, the final relationship is:

```text
expected congestion at point = -Σ(expected_mu for constraint c × SF[c, point])
```

Production keeps them separate because the SF map describes where congestion
lands, while the μ forecast describes when each constraint is likely to matter
and by how much. The live forecast uses the two heads to draw possible binding
outcomes rather than relying only on the single expected value shown here.

## What this example intentionally omits

This tutorial is not a replacement for the production path. It omits data
vintages and leakage checks, constraint selection, the full feature set,
calibration checks, rolling walk-forward evaluation, and the P10/P50/P90
sampling step. Those are necessary operational safeguards, but they obscure the
basic two-model story.
