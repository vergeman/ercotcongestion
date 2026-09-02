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

Detection, Magnitude, and Timing ask the same broad questions for constraints
and nodes: did the forecast identify what mattered, put the right amount in the
right place, and get it into the right hours? Their exact calculations differ
because constraints and nodes have different settled signals.

All model, persistence, and climatology profiles for one half are scored on the
same delivery hours and the same subject universe. These Brief grades are
separate from the nodal Scoreboard grades.

### Constraint Grades

Constraint grades compare forecast and settled shadow-price profiles.

**Detection**: did the forecast put the constraints that bound near the top?

Constraints are ranked by their _forecast_ shadow-price total across the
delivery day. The _settled_ label is whether a constraint has a settled
shadow-price row in any delivery hour. (A published `$0` row still counts as an
event.) Detection uses average precision:

* Precision at rank `k` is the share of the first `k` constraints that are
  settled events. Detection is the average of that precision at every settled
  event.
* Example forecast ranking: `[A, B, X, C, Y]`; settled event set: `{C, B, A}`.
  `A` scores `1/1`, `B` scores `2/2`, and `C` scores `3/4`, for Detection of
  `(1.00 + 1.00 + 0.75) / 3 = 0.917`.
* A ranking of `[X, Y, A, B, C]` puts two non-events first and scores
  `(1/3 + 2/4 + 3/5) / 3 = 0.478`.
* Detection does not compare one rank ordering with another. Reordering within
  the _settled_ events, or within the non-events, changes nothing.

`expected_average_precision()` ranks daily forecast totals against these
settled-event labels.

**Magnitude**: did forecast and settled summed shadow prices agree in amount
and by constraint?

```
    Forecast Settled   Shared / Overlap (min)
A    100        80         80
B     20        60         20
--------------------------------
Sum  120       140         100
```

* Average amount = `(forecast total + settled total) / 2` = `(120 + 140) / 2 =
  130`.
* Shared amount = `sum(min(forecast, settled)) = 80 + 20 = 100`.
* Magnitude is `100 / 130 = 0.77`, between 0 and 1. Over- and
  under-forecasting both reduce the score.

`_soft_overlap()` calculates the shared amount divided by the average forecast
and settled amount.

**Timing**: did the detected constraints appear in the correct delivery hours?

The _hourly_ Timing value ranks all constraint-hour cells by forecast shadow
price, then calculates average precision against the settled-event cells. It
converts that result to skill above the hourly settled-event rate:

`skill = (average precision − chance) / (1 − chance)`

Here, `chance` is the share of constraint-hour cells with a settled row. A score
of 0 is no better than random ordering, 1 is perfect, and a negative score is
worse than random.

The displayed daily Timing value applies the same re-scaling to daily Detection;
it is useful as a common scale, but is not an additional timing test.

Worked examples:

* **Daily:** 10 constraints, 2 with a settled row. Suppose the forecast puts
  one event first and the other last: average precision is
  `(1/1 + 2/10) / 2 = 0.60`. The settled-event rate is `2/10 = 0.20`, so daily
  skill is `(0.60 − 0.20) / (1 − 0.20) = 0.50`.
* **Hourly:** 5 constraints over 4 hours gives 20 constraint-hour cells, 2
  with settled rows. If one event ranks first and the other last across the
  pooled 20-cell forecast ranking, average precision is
  `(1/1 + 2/20) / 2 = 0.55`. The event rate is `2/20 = 0.10`, so hourly skill
  is `(0.55 − 0.10) / (1 − 0.10) = 0.50`.

`expected_average_precision()` ranks daily constraints or flattened
constraint-hour cells; `_chance_adjusted()` reports skill above the applicable
settled-event rate.

### Node Grades

Node grades compare forecast and settled nodal congestion, `SPP − system λ`.
Before grading, both profiles are converted to **absolute congestion**. They
measure the size and location of price separation, not whether a node settled
above or below system price.

**Detection**: did the forecast identify the nodes with the largest congestion?

Nearly every settlement point has some nonzero congestion, so a bind/no-bind
label is not selective enough for the headline node metric. Detection ranks
scored nodes by total absolute congestion for the delivery day, selects the top
10% of forecast nodes and the top 10% of settled nodes, then reports their
overlap.

Every scored node competes for the top 10%. Randomly selecting 10% of nodes
captures 10% on average.

Example: with 20 scored nodes, the top 10% is 2 nodes. If the forecast top 10%
is `{A, B}` and the settled top 10% is `{A, C}`, one node is shared, so
Detection is `1 / 2 = 0.50`.

**Magnitude**: did forecast and settled absolute congestion agree in amount and
by node?

This is the same soft-overlap calculation used for constraints, applied to
daily totals of absolute nodal congestion.

Example: the signs are removed before scoring.

```
Node       Forecast   Settled   Forecast |·|   Settled |·|   Shared
IMPORT       -100        +80          100            80         80
EXPORT        +20        -60           20            60         20
--------------------------------------------------------------------
Total                                   120           140        100
```

Magnitude is `100 / ((120 + 140) / 2) = 0.77`. Both nodes receive credit for
their congestion size even though each forecast has the opposite settled sign.

**Timing**: did the detected nodes appear in the correct delivery hours?

Hourly Timing repeats top-10% capture independently in each delivery hour and
averages those hourly captures. The displayed daily Timing value is the same
daily Detection capture, not an additional timing test.

Worked examples:

* **Daily:** the displayed daily Timing value is the same `0.50` Detection
  capture in the example above.
* **Hourly:** with the same 20-node universe, suppose four hourly captures are
  `0.50`, `1.00`, `0.00`, and `0.50`. Hourly Timing is their average:
  `(0.50 + 1.00 + 0.00 + 0.50) / 4 = 0.50`. A random top-10% selection has
  expected capture of `0.10` in each hour.

### Interpretation limits

* The node top-10% threshold is a deliberate attention-capacity choice, not an
  inherent congestion threshold.
* Constraint and node grades share concepts but are not interchangeable
  statistics.
* Profiles are aligned by delivery-hour order when their source timestamps do
  not match exactly.

## Shared metadata

- `metadata.py` — Loads settlement-point metadata and derives hub/load-zone
  types from names when static metadata is absent.
  - Major functions: `load_sp_metadata`, `hub_lz_type`.
  - Called by: `hero_builder.py`, analysis panels, and analysis queries.
