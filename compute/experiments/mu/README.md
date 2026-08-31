# μ experiments

One-off studies for the **forecast layer** — the part that predicts how much
each constraint will bind (its μ). The SF map is held at its chosen operating
point (`window=240, refit=7, λ=1`); these files only ever vary the forecast on
top of it.

## The rule all three obey

Singular scoring harness in this package: `compute.evaluation.mu`.

The panel is built **once**, with every arm's columns present, and each arm is
just a mask that hides some columns. The only thing that differs between two
rows of a result table is the feature set.

NB: The baselines (oracle, persistence, climatology, null) don't depend on the
arm.

Gated bars (pre experiment):
* **existence** — beat yesterday (persistence), top-decile > 0.561;
* **product** — top-decile ≥ 0.60.

These are different questions: persistence's own score sits below the product
bar, so an arm can beat persistence and still not be good enough to ship.

## `feature_ablation.py`: which inputs actually help?

Five arms, each adding a family of features:

* **base**: the plain forecast, no extras
* **lag**: plus recent history of each constraint (yesterday's μ, etc.)
* **geo**: plus location features
* **wx**: plus weather
* **all**: everything at once

Each arm walks the same weeks through the same harness, and the report prints
what each family bought **over base**.

**Result: `all` (lag+geo+wx) ships.** The combined arm was the pick and is the
production feature set.

## `outage_ablation.py`: do per-constraint outages beat a zonal average?

A follow-up arm (plan/0089) that wasn't in the original five, so it's measured
*marginally* on the same panel and harness.

The subtlety: every arm already gets a coarse outage signal, four load-zone MW
totals, the same for every constraint in an hour. That coarse version lives in
**base**. So the real question is whether knowing outages **per individual
constraint** beats that zonal average.

The four rows are `base` (zonal), `all`, `out` (per-constraint), and `all+out`,
and the verdict is the gap `out − base`: positive means per-constraint is worth
it, zero or negative means it collapses back to the zonal fallback we already
had.

**Result: FLAT.** Per-constraint exposure barely edges the zonal fallback and
adds nothing on top of `all`.


## `rerank.py`: are we losing the tail because we rank by the average?

The puzzle: the model beats yesterday whenever we ask "how bad on average", but
loses when we ask it to name the handful of worst nodes. There's a plumbing
reason that could happen even if the model is perfectly good.

We rank nodes by their *average* expected congestion. But an average blends two
very different things into one number: "almost certainly a small bind" and "a
small chance of a huge one" can average out the same, even though only the
second is a genuinely scary node. Yesterday's actual congestion doesn't blend
anything — it's one real bad day, so it points at the extremes more sharply.

So this file takes the exact same forecast and reads it more pessimistically:
instead of the average, rank nodes by top-decile: of the nodes that actually had
the worst congestion that week (the true worst 10%), what fraction did the
ranking also put in its own worst 10%. (1.0 = caught them all, 0.1 = no better
than random.)

**Result: REFUTED.** Reading it more pessimistically doesn't help; it's flat and
then gets slightly worse: top-decile hit score form 0.516 drifts worse to 0.472.
