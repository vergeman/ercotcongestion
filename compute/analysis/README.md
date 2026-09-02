# Analysis

Query-backed analysis primitives used to build the daily Brief, classify and
render its hero copy, and grade settled forecasts. Database reads and assembly
stay separate from the pure projection, classification, and scoring helpers.

## Walkthrough

To get oriented, follow one of the two delivery paths before reading individual
helpers:

1. Start with `hero_builder.py` and `build_hero`. This is the hero assembly
   entry point and shows the data flow from artifact and database reads to the
   classified slots.

2. Read `hero_queries.py` next. Its small readers define the trailing-window
   inputs and reproducible as-of boundaries used by the builder.

3. Follow the assembled summaries into `hero_classifier.py`. The pure `classify_*`
   functions turn inputs into stable buckets; `magnitude_verdict` compares the
   forecast and settled buckets.

4. Finish the hero path in `phrases.py`. `render` maps the slots to the
   controlled segments served to the Brief.

5. For grades, start with `brief_grade.py`, which loads and aligns profiles.
   Then read `grade.py` for the pure metrics applied to those profiles.

6. Use `metadata.py` when a path needs settlement-point classification, and use
   `tests/` for concise examples of each module's boundary and expected output.

## Daily Brief hero

- `hero_builder.py` — Coordinates artifact and compact database-window reads to
  assemble classifier-ready hero slots and conditions for a delivery day.
  * `build_hero()`: loads shared inputs, builds the displayed slots, and may
    build forecast comparison slots from those same inputs.
  * `build_hero_condition()`: builds the load-condition (ERCOT load, net-load,
    actual, wind, solar, etc. queries) slot from the delivery-day.
    * `classify_regime()`: text bucket classification for `summary`
  - Called by: the `api/services/analysis/features/hero.py:get()` hero service,
    analysis panels, and `compute/jobs/render_hero_golden.py`.
    * NB: `render_hero_golden.py`: is for auditing output offline to show all
      the headlines and gauge the repetition. It's not a cron or caching job, it
      outputs text, e.g. `analysis/tests/fixtures/hero_audit_365.txt`

- `hero_queries.py` — Provides as-of, trailing-window db readers and summaries
  for constraints, geography, and load conditions.
  * `load_constraint_days`: daily realized mu sum per constraint in window
  * `load_forecast_constraint_days`: forecasted mu for constraint in window
  * `daily_total`: populate constraint row with sums, pads with zero to maintain
    date alignment
  * `load_constraint_geo`: constraints to "zone shares" by date.
  * `summarize_load*condition(load_load_condition())`: formatted load stats
  - Called by: `hero_builder.py:_load_inputs()`.


- `hero_classifier.py` — Pure "classifier" for the daily Brief hero. Takes queried data,
  classifies them into magnitude, regime, location, exception, and verdict
  "slots". This is to bucket and qualify pseudo-generated text.
  * `classify_slots`
  * `classify_regime`
  * `magnitude_verdict`
  - Called by: `hero_builder.py`, `api/services/analysis/features/hero.py`, and
    `api/services/analysis/panels.py`.

- `phrases.py` — The hero phrase book. Maps classified slots to controlled copy
  segments and renders the final structured hero text.
  - Major functions: `phrase_for`, `render`.
  - Called by: the hero feature service
    (`api/services/analysis/features/hero.py:get()`), analysis panels, and
    `compute/jobs/render_hero_golden.py`.


## Brief grades - /brief (home page) "Forecast Grade" panels

- `brief_grade.py`: Loads forecast and settled constraint/node profiles,
  constructs comparison baselines, and serializes neutral Brief-grade payloads.
  * API grade path and `compute/jobs/materialize_brief_grade.py`:
    * `grade_constraint_profiles`: returns `GradeResult` from aggregating
      forecast/settled mu profiles. Builds the model, persistence, climatology
      grades, send to `grade.py`.
    * `grade_node_profiles`: returns `GradeResult` from aggregating
      forecast/settled node profiles. Builds the model, persistence, climatology
      grades, send to `grade.py`.
    * `serialize_grade_half`: wraps grade profiles for Brief panel response, and
      persisted via materialized_brief_grade.
  * Queries for constraint / node profile generation (shape: time x constraint/node)
    * `settled_mu_profile`
    * `forecast_mu_profile`
    * `settled_node_profile`
    * `forecast_node_profile`

- `grade.py`: Pure per-delivery-day grading calculations. Aligns profiles and
  derives detection, magnitude, timing, calibration, and baseline metrics.
  * `grade_profiles()`: primary profile builder, aggregates all stats and
    scores.
  - Called by: `brief_grade.py`.

### The Grades

**Detection**: Did the forecast pick the right BINDING nodes/constraints?

  * Did the forecasted binding constraints, end up ranked above constraints that
    didn't actually bind. Did we "detect" binding.
  * The statistic is average precision:
    * Precision = true / total (true + false) = relevant / total items
    * Forecast set: sum each constraint's congestion over all hours, and rank
      them, highest to lowest congestion.
    * Realized set: that list of constraints that bound that day
  * Example:
    * My forecast ranking is `[A,B,X,C,Y]`. - forecast order matters.
    * Realized binding set is `{C,B,A}`. (NB: this is a set - no order - here)
    * A: 1/1 = 1.00
    * B: 2/2 = 1.00
    * X: not in bound set, skip
    * C: 3/4 = 0.75
    * Y: skip
  * Average of the hits: (1.00 + 1.00 + 0.75) / 3 = 0.917
  * True / Total: where True is binary, exists in realized set.
  * Contrast with `[X,Y,A,B,C]` where two non-binding constraints are in the
    forecast.
    * (0/1 + 0/2 + 1/3 + 2/4 + 3/5) / 3 = (.33 + .50 + .66) / 3 = 0.48 much lower
  * Detection is not about matching rank vs rank ordering, as barely different
    deltas could skew as error (e.g. rank #5 as rank #6).
  * `expected_average_precision()`: ranks daily forecast totals against the
    settled activity labels.

**Magnitude**: did the forecast have total congestion at the right size and
place? The right constraint?

```
    Forecast Settled   Shared / Overlap (min)
A    100        80         80
B     20        60         20
--------------------------------
Sum  120       140         100
```

  * average mass = `(sum of forecast + sum of realized) / 2` = (120 + 140) / 2 =
    130
  * overlap = `sum( min(forecast, realized) )` - how much did we both agree on =
    (80 + 20) / 100
  * 100/130 = 0.77. (result between [0, 1]).

  * `_soft_overlap()`: the min shared vector / the mean mass (settled) vector;
    calculates that shared fraction.

**Timing**: do forecasts land on the correct subject-hour? A forecast that
correctly identifies a constraint, but has congestion at the wrong hours should
score worse than one that gets both the subject and timing right.
  * Timing (skill) = `Avg Precision - chance` rate: fraction of things that
    bound anyway; then re-scaling so a random guess is 0 and perfect = 1.

  * Start with Average Precision score, calculated same as detection above
    * daily avg precision: sum of constraint's congestion per day
    * hourly avg precision: hourly congestion per constraint - a cell

  * `chance`: dumb ranking score - random fraction of constraints/nodes binding;
    set to `bound.mean()`. This is what the baseline avg precision would approach.

  * `skill`: how much beyond chance = `(avg precision - chance) / ( 1 - chance)`
    * numerator: `avg precision - chance` - how much over a random ranking
    * denominator: `1- chance` most that could have been beaten (e.g. 0% chance,
      perfect 1.0)

  * Example:
    * Haily:
      * 10 constraints, 2 bound today. chance = 2/10 -> 20%.
      * AP = 60% (calculated same as detection)
        * P .... Q bind out of 10 total. P at 1st, Q at last: 1/1 + 2/10 = 1 +
          .2 = 1.2 / 2 -> .60
      * skill = (.60 - .20) / (1 - .20) = .4 / .8 = 50%
    * Hourly:
      * 5 constraints x 4 hours = 20 cells. 2 bind. Rank each by congestion
        (high to low constraint per hour).
      * AP (detection). Top binding cell ranks, other binding cell ranks last.
        1/1 + 2/20 = 1 + .10 = 1.10. Take avg = 1.10 / 2 = 0.55
      * chance = 2/20 = .1
      * skill = (.55 - .1) / 1 - .1) = .45 / .9 = .5

  * `expected_average_precision()` ranks /scores the daily or hourly cells
  `_chance_adjusted()` reports skill above the settled activity rate.

## Shared metadata

- `metadata.py` — Loads settlement-point metadata and derives hub/load-zone
  types from names when static metadata is absent.
  - Major functions: `load_sp_metadata`, `hub_lz_type`.
  - Called by: `hero_builder.py`, analysis panels, and analysis queries.
