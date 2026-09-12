# ERCOT Stress

[TODO: Screenshot / Video]

ERCOT Stress maps where congestion is priced across ERCOT, then recovers the
hidden shift factors behind it. It uses that structure to forecast tomorrow’s
congestion and evaluates its track record after settlement.

[GitHub](https://github.com/vergeman/ercotstress)


## The Four Pages of ERCOT Stress


* Homepage Brief: a daily scan of nodal congestion and constraint shadow prices
  of interest, typically outside their recent p10-p90 30-day range.

* Map: displays nodal congestion, LMPs, and each constraint's electrical
  footprint. Toggle between forecast and settlement data. Hourly playback shows
  _when_ and _where_ congestion occurs.

* Matrix: explore the recovered shift factors and each constraint’s congestion
  contribution to a given node; shows _why_ a node prices the way it does.

* Scoreboard: evaluates the forecast's results over time and compared against
  baselines.


Each page presents a unique lens to explore ERCOT's network topology,
congestion, shift factors, and even an attempt at price forecasting.


## System Price and Congestion

Most retail consumers pay a fixed price for electricity from a single utility,
but wholesale power operates as a nodal market, with variable prices at
different points throughout the grid. In Texas, [ERCOT](https://www.ercot.com/)
operates the electrical grid and related market operations.

Now imagine an electrical grid without any delivery restrictions and unlimited
transmission capacity. Electricity generated from wind turbines in the south
could power Houston, while daytime eastern solar could reach Dallas. With no
transmission limitations, power could flow freely from point to point, and the
marginal cost of serving the next MW of electricity would be the same throughout
the grid. This base price is known as the **system price (λ)**.

Realistically, there are only a finite number of transmission lines, each with
their own capacities and operating limits. Once a path is saturated, generation
must be dispatched differently and prices diverge, as cheaper, distant
generation is typically replaced by more expensive, local generation.

This added cost that arises from adhering to transmission limits creates a price
difference between locations called **nodal congestion**. Combined with the
system price, they set the nodal price, or **LMP** (Locational Marginal Price):
the price of electricity at that particular node.

    LMP = System Price (λ) + congestion


## Constraints: the Hidden Layer

The transmission limitations imposed throughout the grid are called
**constraints**. A constraint isn't a node, but describes an imposed restriction
or rule. For example, constraints can be set to reduce power flow for
transmission line maintenance; to maintain operating limits and stability on a
line, or enact export restrictions across large regional areas. Operators do not
continuously run lines at their physical maximum, rather, they set constraints
across the grid to keep a healthy margin between actual flow and physical limits
so the grid operates reliably and with redundancy.

ERCOT's constraint format is: `Monitored Element | Contingency`. A **monitored
element** may be a line, transformer; typicall described using a regional
shorthand or an opaque identifier, like `6437`. A constraint imposes a
restriction under a specified **contingency**. Both elements and contingencies
use a heavily contracted naming schema, consisting of 3-4 letter station / unit
names, a voltage suffix (`8` for 138kv, `9` for 69kv, `5` for 345kv, etc) with
transformers showing two numbers in sequence to indicate the voltage change.
Generally, these require knowledge of the network topology to decipher.

Types of constraints:

* **Transmission:** a line or transformer, usually a corridor between stations.
  e.g. `6830__C | SGRMGRS8`.

* **Radial:** serves a pocket, often associated with sharp local spikes and a
  tight footprint. e.g. `OLINGR_FMR1 | BASE CASE`

* **GTC:** "General Transmission Constraint" - an operator-defined general
  stabilization or voltage restriction, whose footprint can encompass entire
  regions. e.g. `WESTEX | BASE_CASE` (West Texas Export), `NELRIO | BASE_CASE`
  (North Edinburg–Rio Hondo)

Types of contingencies:

* Single (`S`) or double (`D`) outage; e.g. `6830__C | SGRMGRS8` or `6830__C |
  DGRMGRS8`.

* Transformer (`X`), Multi-Element (`M`) outage e.g. `SNYDR_FMR1 | XCGR89`

* `BASE CASE`: nothing failing, but a restriction in place during normal
  operation.



### Constraint Limits and Shadow Prices

Once flow on a constrained element reaches its limit, the constraint is said to
_bind_. Binding means the limit is active but not violated. ERCOT dispatches
generation and manages the grid to keep flow below limits, but sometimes a limit
is reached and a constraint binds, creating a **shadow price**, or μ: a measure
of the economic pressure at the bottleneck, if that line's limit could be
relaxed by 1 additional MW.

A high shadow price is not strictly the fuel cost of additional generation; it
is the system-wide cost of preserving that constraint limit when replacing the
next infeasible MW with the best feasible alternative. ERCOT publishes an hourly
list of binding constraints and accompanying shadow prices, but their location
and effect on nodal prices throughout the grid is impossible to trace by name
alone.

These constraints form a hidden layer that drives congestion, but remains
invisible on a map. However, by using a ridge regression on publicly available
data, it is possible to recover an estimated shift-factor matrix to measure a
constraints effect on every node in the grid. In turn, we can visualize a
constraint's "nodal electrical footprint," and geo-locate that hidden layer.

#### Always on Constraints

A handful of constraints appear almost daily to shape regional flow patterns.

For example, `LPLMK_LPLNE_1`, a 115 kV line in West Texas appears in 95.9% of
the trailing 365 days. `HARGRO_TWINBU1_1`, `6437__F`, `NELRIO`, and `E_PASP`
also appear more than 90% of the days in a six-month window.

However, always-on and expensive are not the same, as frequency and cost are
different. Some constraints appear frequently but have shadow prices near zero,
while others rarely appear, but carry substantial congestion cost. For example,
the `DIESEL_FMR1` constraint appeared in 82.3% of the trailing 365 days, but had
a shadow near $0, while `LAKENA_SAMATH1_1` appeared 79.6% of the time, but with
a daily shadow-price total of $1,558.

> **[SCREENSHOT: always-on constraints.]** The Brief's ranked-constraints panel,
> or `LPLMK_LPLNE_1` located on the Map as a West Texas footprint.


### Shift Factors, Shadow Prices, and Congestion

While a shadow price (μ) tells us how costly a particular constraint is; it does
not say which nodes and LMP become expensive or cheaper. Shift factors provide
that missing relationship between constraints and nodes; a number between `[-1,
1]` that represents how much more flow would travel along the constraint if 1 MW
were injected at that node.

Recall that a component of each nodal price is congestion, which can be further
decomposed:

    congestion = −Σ SF·μ

The `SF` represents a matrix of _shift factors_, with constraint rows and node
location columns. For example, an `sf` value of -0.4, means an injection of 1 MW
at that node would reduce flow along that constraint by -0.4 MW.

For a binding constraint, there are typically two sides to describe flow; red
(scarce, expensive), and blue (plentiful, cheap). When a shift factor is
negative, the congestion term (`−SF·μ`) is positive, so the price increases. On
the other hand, a positive SF results in negative congestion, lowering the
price.

* `sf` < 0 - red: import side that receives power along the saturated path.
  Power is scarce and needed, so congestion increases nodal price above system
  price to attract generation.

* `sf` > 0 - blue: export side that is sending generation but often trapped
  behind a limit; congestion pushes the nodal price below the system price.
  (Even negative.)


This two-sided electrical footprint often arises at the seam between a load
(demand) pocket and a generation (supply) pocket.

Since congestion is a sum, the contributions from different constraints on a
specific node can cancel out. One active constraint may push its price up while
another pushes it down, leaving total congestion near zero even though both
constraints affect that location.


## Recovering the Shift Factors Matrix

ERCOT does not publish shift factors to the general public, limiting such
information to market participants (the "secure area"). Shift factors are
considered Critical Energy Infrastructure Information (CEII) as they're
representative of topology and can identify electrical vulnerabilities and
contingency responses.

However, all the terms in our congestion equation aside from the shift factors,
are publicly available; the shadow prices μ, the settled system price λ, and
LMPs at every location are settled and known. Given we can calculate congestion
from the difference between our system price and LMP, this leaves the shift
factors as the sole unknown that we can solve for, using a ridge regression.


1. `LMP = System Price (λ) + congestion`
2. `congestion = LMP - System Price (λ)`
3. `congestion = −Σ SF·μ`  (where μ per constraint from EROCT data)
4. this gives us a linear combination (recall, `Ax=B`)

```
C = −M · SFᵀ
```

* **`C`**: congestion, **hours × settlement points**. The congestion component
  of LMP (`LMP − λ`) at each settlement point.
* **`M`**: shadow prices, **hours × constraints**. `$/MWh` per constraint per
  hour; zero when not binding.
* **`SF`**: **constraints × settlement points**. How hard each constraint pushes price at
  each settlement point.

ERCOT provides data for `M` and `C`, and we solve for `SF` by ridge regression
on a trailing 240-day window, refit weekly. There are no covariates (load,
weather, etc) or additional inputs in this fit.

The recovered shift factors are verified against settlement data. Combined with
ERCOT’s settled shadow prices, they can reproduce the observed congestion
pattern across nodes; with a residual error measured on every weekly refit.

As an independent cross-check, ERCOT also publishes an ESSP list (Electrically
Similar Settlement Points) of nodes that should have identical shift-factor
signatures. In this example below, Node A, and Node B are in the same group, as
they have the exact SF values for all constraints.

```
                        Node A*   Node B*   Node C
  Constraint 1          −0.2      −0.2      0.5
  Constraint 2           0.1       0.1     −0.3
  Constraint 3          −0.4      −0.4      0.0

* nodes with exact shift factors matches are grouped
```

Across the 20 groups in the ESSP list, the recovered map matched every one of
ERCOT’s published groups.

We can then enrich each settlement price node (column) with public location data
(EIA-860) to attach latitude / longitude coordinates, which generates the
"electrical footprint" to visualize the constraint on a map.

More details are available at
[`docs/MODELS.md`](https://github.com/vergeman/ercotstress/blob/master/docs/MODELS.md)
and
[ESSP](https://github.com/vergeman/ercotstress/tree/master/compute/evaluation).


---

## Forecast

Given we now have our market-implied shift factors from our ridge regression,
all the pieces are in place to make a shadow price forecast, and in turn, a
congestion forecast.

The shift factor matrix is refit weekly since network topology is thought to
remain fairly static, while the forecast for tomorrow's day-ahead market (DAM)
shadow price is run daily, asking for every constraint and hour:

* What is the probability it binds? `P(bind)`
* If it binds, how large is the shadow price? `E[μ | bind]`

The expected shadow price per constraint-hour is the product of the two:

    E[μ] = P(bind) × E[μ | bind]

The probability model handles the many zero-shadow-price (quiet) hours, while
the magnitude model learns from hours with non-zero settled shadow prices. This
is a two-part model, since any non-zero shadow price must first bind.

Both models (probability and expectation) use the same inputs: expected load,
wind, solar, outages, calendar, recent constraint history, and the recovered
location.

The predicted μ values are then projected through the shift factor matrix (`−Σ
SF·μ`) at every location to create tomorrow's nodal map. Details are in
[`docs/MODELS.md`](../../../docs/MODELS.md).


## Evaluation

The forecast is evaluated using three metrics:

* **Rank ρ (Spearman):** rank the forecast congestion against market settled congestion,
  and compare the ordering. Higher values reward getting the relative picture
  right, even if the dollar amounts are off.
* **Top-Decile Hit:** did it identify the most-congested tenth of nodes? How
  many of the forecast's top congested nodes were also top market congested nodes.
* **Sign Agreement:** did it get the up-versus-down direction right relative to
  system price?

The model's metrics are also compared to three "baseline" runs:

* **Persistence**: simply repeating yesterday's output. This baseline performs
  well in stable conditions.
* **Climatology**: uses a trailing average of historic values.
* **Oracle**: uses realized shadow prices to isolate any error to the recovered
  shift-factor map, rather than the shadow-price forecast. This is the ceiling -
  the best the forecast could do in hindsight - as any variation must originate
  from the SF regression


## Case Studies

Examine how the map and forecasts behaved during a specific moment of history.

### Far West Sign Flip: June 20–21, 2025

Overnight, the Permian imported power with congestion around **+$34/MWh**. By
midday, **5.6 GW** of local solar saturated export paths and the area reached
about **−$24/MWh**, turning into an export hub. The nodal map visibly flips from
an expensive receiving side to a cheap exporting side. A constraint
footprint explains the hidden mechanism underneath both images.

TODO: find constraint `LPLMK_LPLNE_1`

> **[SCREENSHOT / TIMESTAMPED LINK.]** The Map at `2025-06-21T00:00Z` and at
> midday, plus its settled grade versus persistence when pulled from graded history.
> Introduce it with
> a static shot of a steady West Texas footprint first, such as `LPLMK_LPLNE_1`, so
> the reader sees the two sides before watching them swap.


### Rabbit Hill: February 19–21, 2025

A winter morning peak from a radial overload in an Austin suburb. At 6 a.m. on
February 20, local congestion reached **+$5,977/MWh** and fell to **+$242 by
noon**. The constraint peaked at **$7,577** on the 20th versus **$323** the day
before.

> **[SCREENSHOT.]** Map at the 6am peak and its grade versus persistence, filled
> only from settled graded history.

### Winter Storm Fern: January 24–26, 2026

A winter storm blankets the state, creating system-wide extremes in which
scarcity and congestion both occur. The widest congestion spread was
**$1,618/MWh** while system λ peaked near **$1,915**. Rio Grande Valley wind was
bottled at **−$1,454**, while `PALACIOS_RN` reached **$20,941** at 0600. The
nodal map makes the spread visible, while the constraint layer shows why a high
system price did not affect every location equally.

> **[SCREENSHOT.]** Map at the peak hour and its grade versus persistence, filled
> only from settled graded history.



## Limitations

While this project is meant primarily as a grid-explorer, there are a handful of
model limitations to keep in mind:

* Persistence is at times a better model. Since weather and electricity demand
  is often the same as the day before, this baseline tends to perform well and
  at times better than the model.

* The Shift-factor matrix can drift, as it is fit weekly with values implied
  from the market - an inexact proxy - compared to official ERCOT values.

* Binding is rare when examined over the entire day. Most hours, particularly
  off-peak, has no binding, no congestion. The grid is quiet by default.

* Recovered shift factors are price-implied estimates, not ERCOT’s official
  PTDFs or market-network model.
