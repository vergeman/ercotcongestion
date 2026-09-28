# Models

# Ridge Regression and Implied Shift Factors

## Example Data Set and Model

Suppose we have three delivery hours, two binding constraint keys, and two
settlement points. A constraint key is the pair
`ConstraintName|ContingencyName`.

**M**: matrix **μ** of shadow prices - (hours x constraints). Rows are hours,
columns are constraint | contingency pairs, each cell is a shadow price, μ.

| Hour  | `NORTH_LINE|BASE` | `SOUTH_LINE|OUTAGE_1` |
|-------|------------------:|----------------------:|
| 01:00 |                10 |                     0 |
| 02:00 |                 0 |                    10 |
| 03:00 |                10 |                    10 |


**C**: matrix of DAM congestion - rows are hours, columns are settlement points.
Each cell is the node's congestion component: `LMP - system_lambda`, LMP minus
the system price, resulting in congestion.

| Hour  | NORTH_SP | SOUTH_SP |
|-------|---------:|---------:|
| 01:00 |       −6 |        2 |
| 02:00 |       −2 |       −4 |
| 03:00 |       −8 |       −2 |

To calculate congestion at a node, we take the product of the constraint's
shadow price and the shift factor - `SF` - for that constraint:

```text
C = −M · SF + residual

(hours x nodes) = (hours x constraints) · (constraints x nodes)
```

We are not given the `SF` matrix, this is the unknown we solve for using a ridge
regression. The `SF` entries are the **coefficients**, or Beta. Each shift
factor describes how much a 1 MW injection of power at that node increases, or
decreases power flow along that constraint.

Using our three hour, two constraint, two node example, we can solve to get SF
values using matrix multiplication and isolating each SF cell value.

```

C                             =       -   M                                *           SF (solved for)

hr NORTH_SP    SOUTH_SP                    NORTH_LINE     SOUTH_LINE                       NORTH_SP   SOUTH_SP
1    -6            2                          10              0            NORTH_LINE        0.6       -0.2
2    -2           -4                           0             10            SOUTH_LINE        0.2        0.4
3    -8           -2                          10             10

   C = - M * SF
  -6 = - [10 * sf(0,0) +  0 * sf(1,0)], sf(0,0) = 0.6       2 =  -[10 * sf(0,1) +  0 * sf(1,1)], sf(0,1)  = -0.2
  -2 = - [0  * sf(0,0) + 10 * sf(1,0)], sf(1,0) = 0.2      -4  = -[ 0 * sf(0,1) + 10 * sf(1,1)], sf(1,1)  = 0.4
```


## Basic Regression

In the simplest case, regression fits a line, `y ~ a + bx`.

* `y` is a settlement point's congestion price.
* `a` is the intercept, the predicted outcome when `x = 0`
* `b` the slope that says how much that prediction changes when `x` rises by one unit.

* `x` is a constraint's shadow price
* When shadow price is zero (`m = 0`), there is no congestion (`c = 0`); this sets `a = 0`.

```text
 y ~ a + bx
 C ~    -M * SF
```

**1. One hour, one constraint, one node.**

* At 01:00, North Line's shadow price is `10`.
* NORTH_SP congestion is `−6`.
* We can think of a point on a graph like (shadow, congestion), (10, -6), and
  we're fitting the slope of the line.

```text
y  = b x
-6 = b * 10

b  = -0.6
```

**Trivial OLS**

Ordinary least squares (OLS) chooses `b` to minimize this squared error: `(−6 −
10b)² = 0`. This is `(y_realized - y_predicted)`, where:
* `y_realized` is the actual value of `y`, -6.
* `y_predicted` is our congestion equation, `b * 10`, or `b * shadow price`.

The minimized error for this equation is zero when `b = −0.6`.

(Note `b` is negative for this example)

**2. Multiple hours, one constraint, one node.**

Expand to three hours. OLS now chooses one slope to minimize the *sum* of three
squared errors:

```text

hour             shadow                         congestion
           x_N = M[North Line]               y   = C[NORTH_SP]

01:00             10                               -6
02:00              0                               -2
03:00             10                               -8


min:    y_realized - y_predicted (xb)
min:  (−6 − 10b)² + (−2 − 0b)² + (−8 − 10b)²

b = sum xi * yi / sum xi^2  (derivative wrt to b)

b = (10 x −6 + 0 x −2 + 10 x −8) / (10^2 + 0^2 + 10^2)
  = −0.7
```


The fitted values are `(-10 * .7, 0 * .7, 10 * .7)` -> `(−7, 0, −7)`, compared
with observed `congestion = (−6, −2, −8)`. This has a squared-error total of
`6`:

```text
squared error = (-7 - -6)^2 + (0- -2)^2 + (-7 - -8)^2
              = (-1)^2 + (2)^2 + (1)^2 = 1 + 4 + 1 = 6
```


**3. Add the second constraint**

Using both shadow price columns, but now fitting one coefficient for both
constraints across the same three hours. Recall our original tables above for M,
that give us the shadow prices for `NORTH_LINE` `(10, 0, 10)` and `SOUTH_LINE`,
`(0, 10, 10)` at each hour.


```text
C[hour, NORTH_SP] = - [b_NORTH x M[hour, NORTH_LINE] + b_SOUTH x M[hour, SOUTH_LINE]]

hour    Congestion NORTH_SP  =  - μ NORTH * b_NORTH   +  μ SOUTH * b_SOUTH

01:00:              −6       =  -      10 * b_NORTH   +        0 * b_SOUTH
02:00:              −2       =  -       0 * b_NORTH   +       10 * b_SOUTH
03:00:              −8       =  -      10 * b_NORTH   +       10 * b_SOUTH
```

Use OLS to minimizes the sum of the three squared differences: `b_NORTH = 0.6`,
`b_SOUTH = 0.2` make all three differences zero.

As a reminder, the model is `C= -M * SF`, note the negative M, but our `SF` values
are positive.

**4. Add the second node**

Repeat the three-hour OLS steps with `SOUTH_SP` observed congestion `(2, −4,
−2)`. These coefficients are `b_NORTH = -0.2` and `b_SOUTH = 0.4`. Now with
multiple nodes, our vector of coefficients become a matrix - a SF matrix:

```text
hour    Congestion SOUTH_SP  =  - μ NORTH * b_NORTH   +  μ SOUTH * b_SOUTH

01:00:               2       =  -      10 * b_NORTH   +        0 * b_SOUTH
02:00:              -4       =  -       0 * b_NORTH   +       10 * b_SOUTH
03:00:              -2       =  -      10 * b_NORTH   +       10 * b_SOUTH
```

We can arrange these b_NORTH and b_SOUTH values for each node in a matrix:

```text
                  NORTH_SP  SOUTH_SP
B[NORTH_LINE]        0.6      -0.2
B[SOUTH_LINE]        0.2       0.4

Congestion = - Shadow *  Shift Factors
C (3 hours × 2 points) = - M (3 hours × 2 constraints) x SF (2 constraints × 2 points)
```

## Matrix (Vanilla) Regression

Real data will not fit so neatly; but we still aim to minimize sum of squared
errors, over all hours and points, moving to a matrix form of OLS:

```text

model: C = - M * SF

minimize the sum of squares residuals: realized - predicted

residual (R) = C realized - (-M * SF)
             = C  +  M * SF

minimize ||R||^2 over SF:  || C + M * SF || ^2

    || C + M * SF ||^2   = 0

take derivative wrt to SF (or B) and set to 0

    2Mᵀ * (C + M * SF)   = 0

divide 2 both sides

    Mᵀ(C + M * SF)       = 0

distribute Mᵀ

    MᵀC + MᵀM * SF       = 0

move MᵀC to other side

    MᵀM * SF = -MᵀC

move negative around

    MᵀM * -SF = MᵀC
```

This resembles a new system of equations with matrix unknowns, like `A x = b`,
and in regression our `-SF` is usually `B`, the regression coefficient matrix.

| `A x = b` | `MᵀM * -SF = MᵀC`                |
|-----------|----------------------------------|
| `A`       | `Mᵀ M`                           |
| `x`       | `-SF` - unknown coefficients (B) |
| `b`       | `Mᵀ C`                           |



### Collinearity and Ridge

#### Collinearity

Constraints often bind together, so their shadow price columns can be nearly
identical; the fit then has little evidence for how to divide a price effect
between them. For a one-point fit, suppose two constraints have **identical**
shadow prices across three hours:

| Hour | `M[A]` | `M[B]` | `C` |
|------|-------:|-------:|----:|
| 1    |     10 |     10 |  −6 |
| 2    |     20 |     20 | −12 |
| 3    |      0 |      0 |   0 |

OLS asks what coefficients `SF[A]` and `SF[B]` minimize squared prediction
errors. Every hour can fit when `SF[A] + SF[B] = 0.6`: `(0.6, 0)`, `(0.3, 0.3)`,
and `(0, 0.6)` - all give predictions of `(−6, −12, 0)`. OLS has no way to pick
one pair; this is collinearity.


#### Ridge

To address this we add a penalty for large coefficients by adding a "ridge" - a
series of values along an identity matrix.

* lambda λ: factor


```text
vanilla regression minimize over SF:

    || C + M * SF ||^2

ridge regression minimize over SF + ridge

    || C + M * SF ||^2 + λ ||SF||^2

take derivative wrt to SF (or B) and set to 0

    2Mᵀ * (C + M * SF) + 2 λ SF      = 0

divide 2 both sides and write λ SF as (λI) SF - identity matrix

    Mᵀ(C + M * SF)  +  (λI) SF       = 0

distribute Mᵀ

    MᵀC + MᵀM * SF  +  (λI) SF       = 0

group SF terms

    MᵀC + (MᵀM + λI)SF               = 0

move MᵀC to other side

    (MᵀM + λI)SF                     = -Mᵀ C

```

* `I` is an identity matrix of constraint x constraint
* `λ ≥ 0` sets the penalty strength.
* `λ I` affects only the diagonal of `Mᵀ M`. This is the “ridge”, and usually pulls fitted
coefficients toward zero.

Using our previous collinear example with `λ = 100`

```text

(MᵀM + λI)SF                     = -Mᵀ C

        [10  10]              [10  20  0]
M   =   [20  20]      Mᵀ   =  [10  20  0]
        [ 0   0]

          [10  20  0] [10  10]
MᵀM   =   [10  20  0] [20  20]
                      [ 0   0]

          [10² + 20² + 0²,   10² + 20² + 0²]
      =   [10² + 20² + 0²,   10² + 20² + 0²]

          [500  500]
      =   [500  500]

λI    =   100 * [1 0]  = [100  0]
                [0 1]    [0  100]

MTM + λI = [600 500]
           [500 600]


-Mᵀ * C = - [10 20 0] * [ -6
            [10 20 0]    -12
                          0 ]

        = - [10 * -6 + 20 * -12 + 0]
            [10 * -6 + 20 * -12 + 0]

        =  [300
            300]

[600 500] SF = [300
[500 600]       300]

600 SFa + 500 SFb = 300
500 SFa + 600 SFb = 300

SFa = SFb = 3/11 = .273

```

The penalty results in two shift factors having an equal split, leaning toward
zero, but it doesn't necessarily reveal which constraint actually contributed
more.


## ERCOT

Production inputs follow the same layout, with many more rows and columns. The
`M` is `ercot_dam_shadow_prices`, from the NP4-191-CD DAM binding constraint
report, while `load_congestion_panel` uses DAM settlement point prices and
subtracts the matching hourly `system_lambda` to form `C`.

Below is a shape of ERCOT records:

```text
M: hours x constraint keys

interval_ts (UTC)       NORTH_LINE|BASE  SOUTH_LINE|OUTAGE_1  ...
2025-06-01 00:00                10.00                  0.00  ...
2025-06-01 01:00                 0.00                 14.20  ...
2025-06-01 02:00                 0.00                  0.00  ...
...                              ...                   ...   ...
2026-01-26 23:00                 7.50                  0.00  ...


C: hours (same as above) x settlement points

interval_ts (UTC)       NORTH_SP  SOUTH_SP  ...
2025-06-01 00:00           −6.00      2.00  ...
2025-06-01 01:00           −2.84     −5.68  ...
2025-06-01 02:00            0.00      0.00  ...
...                        ...         ...  ...
2026-01-26 23:00           −4.50      1.50  ...
```

Each fit uses a trailing **240-day** window, about `240 x 24 = 5,760` potential
hourly rows. It refits every **7 days** - the regression is run on a weekly
cadence, dropping the last 7 days when adding the new 7 days - which means ~ 233
days are shared between each run. Constraints require at least 25 positive
shadow price _hours_ to be included in the window. Missing cells in `C` are filled
with zero in the current solver.

The production solve standardizes each retained `M` column by its in-window
standard deviation, with a floor of `100`: `scale = max(std dev, 100)`. Since
shadow prices can vary (e.g 10 vs 100) but produce the same congestion, we need
to scale the shadow prices. For example, a shadow price of 10 (vs 100), would
require a coefficient 10x as large for the same predicted congestion. Without
scaling, the ridge would penalize that first coefficient much more because it
would be so much larger. Re-scaling makes the ridge penalty more equitable
across constraints, and a floor makes sure tiny shadow prices (small std
deviations) don't distort the values

```text
M

hours   NORTH_LINE     SOUTH_LINE     |  scaled std dev (100) NORTH_LINE    scaled std dev (1000) SOUTH_LINE
0100        0                0                      0                             0
0200      200             2000                      2                             2
0300        0                0                      0                             0
0400      200             2000                      2                             2

C

hours    NODE
0100       0
0200     -20
0300       0
0400     -20

  C @ 0200 =  -M * SF
      -20  =  -(200 * SF_NORTH + 2000 * SF_SOUTH)

```

Since these move together, we can't identify how to split the `(SF_NORTH, SF_SOUTH)`:
`(.10, 0)`, `(.05, .005)`, `(0, .010)`

Without scaling, a small `SF_SOUTH` can explain all the congestion because the
shadow price is 10x larger. So ridge would favor the smaller coefficient because
it penalizes larger numbers.

By scaling, (std dev of 100, and 1000), both shadow columns are now `(0, 2, 0,
2)`. Now given the scaled columns, a ridge regression - during the fit - would
handle them equally, not penalizing one relative to the other. Calculating the
SF gives _identical_ values of ~4.706. So using our scaled `M` and `SF`, we get
2 * -4.706 or Congestion `C` of -9.4 for each line. Total congestion (-9.4 +
-9.4) is -18.8, which is close to -20.

Each `SF` is scaled back, (-4.706 / 100 = .04706, -4.706 / 1000 = .004706), to
match the original scale of the shadow price.

If we didn't scale, the `SF` would be ~(.00099, .009901), so each would
contribute to total congestion: 0.20 + 19.80 = 20. So all the congestion would
be attributed to `SOUTH_LINE`, but by scaling they were equally attributed.

This will **not** recover actual network shift factors, but it's a reasonable
estimate toward building an implied, price-based shift factor map.



* NB: std dev is sqrt [sum (point-mean)^2]

---

# Two-Head Model: Forecasting Shadow Prices

The ridge regression uses realized shadow prices `M` and congestion `C` to fit
`SF`, but for a future delivery day we don't have `M`. So we forecast μ,
estimating a DAM shadow price for each `(hour, constraint | contingency)`.

The forecast answers two questions:

1. **Will the constraint bind?** The bind head predicts `p_bind`, which is `P(bind)`.
2. **If it binds, how large will μ be?** The severity head predicts `mu_gbm`, an
   estimate of `E[μ | bind]`.

Combining the heads gives an expected shadow price:

```text
E[μ] - P(bind) x E[μ | bind] = p_bind x mu_gbm
```

The forecast is split in two, largely because when a constraint does not bind,
it's shadow price is zero; and when it binds, its expected magnitude is
`mu_gbm`. This creates a natural two-stage forecast.


## Example: P(bind)

Imagine four the hours below for each constraint (North, South):

| Past hour | Constraint | Shadow Price `μ` | `y_bind` (`|μ| > 1`) |
|-----------|------------|-----------------:|---------------------:|
| 1         | North      |               40 |                    1 |
| 2         | North      |               60 |                    1 |
| 3         | North      |               80 |                    1 |
| 4         | North      |                0 |                    0 |
|-----------|------------|-----------------:|---------------------:|
| 1         | South      |                0 |                    0 |
| 2         | South      |               20 |                    1 |
| 3         | South      |                0 |                    0 |
| 4         | South      |                0 |                    0 |

A trivial classifier could observe the P(Bind): `p_bind(North) = 3/4 = 0.75` and
`p_bind(South) = 1/4 = 0.25`.

## Example: E[μ | bind]

To estimate severity, keep only binding rows:

* North: the shadow prices are `40, 60, 80`, so a simple conditional estimate is
their average, `60` (40 + 60 + 80) / 3.
* South the only binding observation is `20`, so its conditional estimate is
`20`.

Note, we do not average in the zero hours, as it mixes binding frequency with
severity.

| 17:00 | `p_bind` | `E[μ | bind]` |           `E[μ]` |
|-------|---------:|--------------:|-----------------:|
| North |     0.75 |            60 | `0.75 × 60 = 45` |
| South |     0.25 |            20 |  `0.25 × 20 = 5` |

These expected values do not mean the actual North shadow price will be `45`. In
this setup it is zero if the key does not bind and has a binding severity whose
average is `60`. The expected value averages across those possibilities. It was
chosen for this forecast because congestion tends to cluster together, so its a
sensible estimate when considering blocks of congestion.

## Example: From μ to congestion using SF

Using our previous SF regression, each SF row corresponds to a constraint |
contingency key, and each column to one settlement point:

| Key   | `SF[NORTH_NODE]` | `SF[SOUTH_NODE]` |
|-------|---------------:|---------------:|
| North |            0.6 |           −0.2 |
| South |            0.2 |            0.4 |

Putting the expected shadow prices into one row, `E[M] = [45, 5]`. The expected
congestion row is the same matrix multiplication as before:

```text
E[C] = −E[M] · SF

NORTH_NODE: −(45 × 0.6 + 5 × 0.2) = −28 $/MWh
SOUTH_NODE: −(45 × −0.2 + 5 × 0.4) = +7 $/MWh
```

Repeat for every forecast hour. The result is an (hours x settlement points)
congestion forecast. The two heads forecast shadow prices; SF maps those
forecasts to points.

## ERCOT Model

The production panel has row (hour) and candidate constraint
| contingency key, indexed by `(interval_ts, key)`:

| `interval_ts` | `key`                 | features                                                 | `y_bind` | `y_mu` |
|---------------|-----------------------|----------------------------------------------------------|---------:|-------:|
| 17:00         | `NORTH_LINE|BASE`     | net load, hour, recent North binds, North geography, ... |        1 |     40 |
| 17:00         | `SOUTH_LINE|OUTAGE_1` | net load, hour, South history and geography, ...         |        0 |  `NaN` |


Labels come from historical DAM shadow prices:

* `y_bind` is `1` when `|μ| > 1` and `0` otherwise
* `y_mu` is `|μ|` on binding rows and `NaN` on nonbinding rows.
* Forecast-day labels are never used as features.

Both heads use the same feature columns, but the binding classifier trains on
all candidate rows and the severity regressor trains only on binding rows.

There is one pooled model for all keys for each head, rather than a separate
model for each constraint. So constraints with little history benefit from the
patterns of other constraints, but at the expense of uniqueness.

The daily fit uses the preceding 240 days. There are ~ 86 covariates; prominent feature groups are:

| Class                         | Varies by                | What it carries                                |  n |
|-------------------------------|--------------------------|------------------------------------------------|---:|
| **Load forecast** (zonal)     | hour                     | MW demand per weather zone                     |  9 |
| **Wind forecast** (regional)  | hour                     | forecast per region + lower bound              |  7 |
| **Solar forecast** (regional) | hour                     | forecast per region + lower bound              |  8 |
| **Outages** (zonal)           | hour                     | MW out per zone, total + renewable             |  8 |
| **Derived**                   | hour                     | `net_load`, `wind_band`, `solar_band`          |  3 |
| **Calendar**                  | hour                     | hour, day-of-week, month, weekend, cyclic hour |  6 |
| **Binding history**           | day × constraint         | recent bind counts & magnitudes                |  6 |
| **Lagged μ** (`lag`)          | day × constraint         | recent realized magnitude (persistence)        |  4 |
| **Geography** (`geo`)         | day × constraint, weekly | the stage-2 SF location bundle                 | 14 |
| **Weather-response** (`wx`)   | day × constraint, weekly | how the constraint's μ tracks each forecast    | 20 |
| **Constraint identity**       | constraint               | smoothed per-key bind rate (`key_bind_rate`)   |  1 |

The first six classes (41 grid-state columns + calendar) are constraint-blind,
the same value for every constraint in a given hour. The `history`, `lag`,
`geo`, and `wx` differentiate constraints in the same hour by their past,
location, and weather response.

### Histogram gradient-boosted Classifiers

A decision tree repeatedly splits rows by feature thresholds: for example,
`net_load > 70,000`, then `binds_7d > 2`. Each tree has a yes/no path,
descending to another feature for a yes/no decision. The final group - the
leaf - gets a prediction. For example, if there are 10 rows, and 8 leaves bind,
then the next forecast row walks the tree and ends up in the bin and is assigned
that probability.

Gradient boosting: this is a modification of the simple decision tree, that
updates or adjusts the probability of the leaf with every new observation; each
new tree improves the errors of the combined trees. Because binding can be
somewhat abrupt, while a logistic regression could track thresholds, learning
that constraints bind when net load is high > X, and wind is low < Y, etc.,
boosting can learn refinements when that rule might not hold, even under
"binding" conditions.

Histogram: means features values are initially grouped into bins and searched
for splits, which makes fitting large panels faster.

Learn more about it from [`sklearn.ensemble` library: Histogram based Gradient
Boosting](https://scikit-learn.org/stable/modules/ensemble.html#histogram-based-gradient-boosting)


```python
# fit_bind_head

model = HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.06, max_leaf_nodes=31,
        min_samples_leaf=100, l2_regularization=1.0,
        early_stopping=False, random_state=seed)
```


```python
# fit_mu_head

model = HistGradientBoostingRegressor(
        max_iter=200, learning_rate=0.06, max_leaf_nodes=31,
        min_samples_leaf=50, l2_regularization=1.0,
        early_stopping=False, random_state=seed)
```

* `max_iter`: 200 number trees (not iterations)
* `learning_rate`: scales each tree's score contribution
* `l2_regularization`: penalizes over-fitting; tree leaf values
* `random_state`: set for repeatable randomization


### Outputs and Forecasted Expected Value

The bind head turns its combined tree score into a binding probability; the
severity head returns a number.

The classifier outputs the binding probability with `predict_proba`.

The severity regressor outputs `mu_gbm`, but applies a `$1/MWh` lower floor, and
also fits and clips some magnitudes to handle extreme shadow prices. Details can
be found in the
[walkthrough.py](/compute/experiments/model_tutorial/walkthrough.py)

Together their product is the expected shadow price (`M`): `predict_proba *
mu_gbm` for each settlement price (node.)

And this expected shadow (`M`), is multiplied by our shift factor (`SF`) to get the
congestion forecast (`C = -M * SF`)
