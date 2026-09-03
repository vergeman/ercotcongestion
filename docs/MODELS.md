# The μ Model

Two stages. First recover each constraint's electrical footprint from prices
alone (the SF map) and turn it into a location. Then forecast congestion with a
two-head model whose features include that location.

---

## 1. Shift Factors From Prices

A constraint key (`ConstraintName|ContingencyName`) has no coordinates. But the
day-ahead market's own identity ties its shadow price to congestion at every
settlement point (SP):

```
C = −M · SFᵀ
```

* **`M`**: shadow prices, **hours × constraints**. `$/MWh` per constraint per
  hour; zero when not binding.
* **`C`**: congestion, **hours × settlement points**. The congestion component
  of LMP (`LMP − λ`) at each SP.
* **`SF`**: **constraints × SPs**. How hard each constraint pushes price at
  each SP.

We observe `M` and `C` and solve for `SF` by ridge regression on a trailing
240-day window, refit weekly. **There are no covariates in this fit**. Only
prices in, shift factors out. Hours are the observations; there is no load,
weather, calendar, or time term.

### Worked example

Three SPs, two constraints. The "truth" (never fed in):

|                          | AMARILLO | AUSTIN | BROWNSVILLE |
|--------------------------|---------:|-------:|------------:|
| `PANHANDLE_LN\|BASE CASE`|     0.90 |   0.05 |        0.02 |
| `VALLEY_LN\|CONT_7`      |     0.00 |   0.40 |        0.55 |

Simulate 400 hours of shadow prices, generate the congestion they cause, then
ridge-solve. Recovered `SF`:

|                          | AMARILLO | AUSTIN | BROWNSVILLE |
|--------------------------|---------:|-------:|------------:|
| `PANHANDLE_LN\|BASE CASE`|    0.897 |  0.051 |       0.019 |
| `VALLEY_LN\|CONT_7`      |    0.001 |  0.398 |       0.548 |

Back to ~0.003 — pulled out of prices, no map used.

---

## 2. Geographic Enrichment: Geolocating The Constraint

Every SP has a fixed lat/lon (plus zone and voltage) from a geocode table. A
constraint's `SF` row says which SPs it acts on and how hard, so the
**|SF|-weighted average of those SP coordinates is the constraint's implied
location**, recovered from prices, with no station-name join.

From the same weights, in one pass:

| feature           | meaning                                                    |
|-------------------|------------------------------------------------------------|
| `geo_lat/lon`     | the electrical centroid — the implied location             |
| `geo_spread_km`   | how spread out its footprint is (local vs. system-wide)    |
| `geo_sp_eff`      | effective # of SPs it sits on (concentration)              |
| `geo_kv_mean/max` | voltage class, \|SF\|-weighted (345 kV backbone vs 138 kV) |
| `geo_zone_<z>`    | share of footprint in each load zone                       |
| `geo_dist_<z>`    | km from the centroid to each zone                          |

From the example: PANHANDLE lands at Amarillo (`sp_eff≈1`, a radial pocket);
VALLEY falls between Austin and Brownsville, biased south (`sp_eff≈2`, a spread
line). `SF` is refit weekly, so a centroid can shift week to week — this is a
per-window feature for the forecast, not a survey.

---

## 3. The μ Forecast

For a delivery day `D`, standing at day-ahead-market close on `D-1`: which
constraints bind during `D`, and how hard? The design matrix is **one row per
(delivery hour × candidate constraint)**, and predicts two targets with two
heads:

* **bind head**: `P(bind)`, a classifier on `y_bind` (0/1)
* **μ head**: `E[μ | bind]`, a regressor on the shadow price

Final forecast = `P(bind) × E[μ | bind]`.

**Both heads read the identical covariates.** They differ only in the rows they
train on: the bind head trains on every row; the μ head trains on **binding rows
only** - that is what makes it a conditional forecast (μ *given* it binds)
rather than an average over mostly-quiet hours. Missing values stay as holes;
the gradient-boosted trees read them natively.

The enriched `SF` geography from stage 2 is fed in here as the `geo_*` block;
the model connects "the north zone is hot today" to "this constraint sits in the
north."

### Row Identity & Targets

Every panel row is addressed by an identifier and carries the two things being
predicted. These are **not** covariates. The identifiers place the row, and the
targets are the answer the model may never see as an input.

| Column         | Role       | Meaning                                                                                                          |
|----------------|------------|------------------------------------------------------------------------------------------------------------------|
| `interval_ts`  | identifier | the delivery **hour** (UTC). One of the two index levels.                                                        |
| `key`          | identifier | the **constraint** (`ConstraintName\|ContingencyName`). The other index level.                                   |
| `delivery_day` | identifier | the CT delivery day the hour belongs to; used only to join day-level features.                                   |
| `y_bind`       | target     | did this constraint bind this hour? `1` if \|μ\| > 1 $/MWh, else `0`. The bind head's target.                    |
| `y_mu`         | target     | the shadow price if it bound, else `NaN`. The μ head's target — the `NaN`s are exactly the rows that head skips. |

A row is one cell: **one hour, one constraint**. `y_bind` and `y_mu` are the
only place day `D`'s own outcome enters the panel; no covariate may be derived
from them.

### The Covariates (Default Run ≈ 86)

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

The first six classes (41 grid-state columns + calendar) are
**constraint-blind**, the same value for every constraint in a given hour, so
they can't rank constraints alone. The `history`, `lag`, `geo`, and `wx` classes
are what make two constraints in the same hour look different: by their own
past, by *where* they are, and by *what weather* moves them. Optional `out_*`
(generation-outage exposure) exists as an ablation arm and is off by default.

Feature sets select by prefix: `base` (grid-state only) -> `+lag` -> `+geo` ->
`+wx` (the default `all`).
