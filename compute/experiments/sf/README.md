# SF experiments

One-off studies to tune and stress-test the **SF map**: the model that predicts
which grid constraints will bind. None of this is production code; each file
answers a question below.

## The question behind all three

The map is refit on a trailing window of recent history. That leaves three knobs
and two doubts:

* `sweep.py`: What settings should it run at?
* `grouping_verdict.py`: does grouping similar constraints improve anything?
* `coverage.py`: how much congestion lands on unseen constraints, and can we fix
  that cheaply?

## `sweep.py`: hyper-parameter settings

Tries every combination of three knobs and grades each one on accuracy:

* **window**: how far back to look
* **refit**: how often to refit
* **smoothing** (lambda ridge) λ

**Result:** the chosen settings are **window = 240 days, refit every 7 days, λ =
1.0** (with `std_floor=100`, `min_hours=25`). A side finding: the smoothing dial
λ had basically no effect; decorative.

## `grouping_verdict.py`: should we group lookalike constraints?

Constraints that move together are hard to tell apart, which can make the fitted
numbers jumpy. This asks whether bundling them into groups makes the numbers
steadier **without** hurting accuracy.

Stability is correlation between two SF maps side by side (non-overlapping
periods.) Stable means no change. Stability is the correlation between these two
maps. High correlation means they move together, so stable. 0 correlation, means
he map jumps / drifts.

**Result: FAIL — grouping does not ship.** Steadiness improved by only
**+0.006** against a required **+0.10**. It didn't hurt model accuracy, so
grouping is "free", it just offers nothing worth the added complexity.

The reason it bought nothing: the groups were tiny, so fixing near-duplicate
constraints didn't touch the real source of drift: congestion patterns that
shift over time.

The grouping algorithm itself lives in `compute/sf_map/model/grouping.py`, it
was built first, and this experiment judged it. Because it failed, the
production runner (`compute/sf_map/model/rolling.py`) leaves `rho_min=None`, so
grouping never runs in the live forecast.

## `coverage.py`: the blind spots, and whether they're worth chasing

Inputs: recorded DAM shadow prices only (`ercot_dam_shadow_prices`, NP4-191-CD).

In a normal week some congestion falls on constraints the recent-history fit has
no column for. This measures that blind spot (~14–19% of the action) and splits
it into three kinds:

* **A — reusable:** seen and fitted in some earlier window, so an old value
  could be carried forward ("warm-start").
* **B — seen but never solid enough** to fit. Needs a faster/looser refit.
* **C — genuinely new.** Nothing to reuse; irreducible.

Outputs:
* No forecast is graded here it's a scope audit, not an accuracy metric.
* uses constraint's weekly `mass`: its shadow price summed over the hours it
  bound.
* `coverage`: fraction of real congestion the model can see [0, 1]
  * the share of the week's total μ-mass on constraints that have a fitted SF
    column. This week is after the 240d window.
  * total binding mass denominator (> MIN_HOURS) is what was seen in the 240d
    fit window (does not include the coverage week)
* `novel_mass`: 1 -coverage, what's new

Only **A** is fixable by reusing old values. The threshold: build that reuse
library only if it would close at least 3 points of the gap.

**Result: FAIL — library not built.** The best a perfect warm-start could recover
was **+0.019** against a required **+0.03**, and even that is optimistic: **70% of
the reusable values are more than 90 days stale.** Not worth building.

## Bottom line

The sweep set the operating point (240 / 7 / λ=1). The two "can we do better?"
ideas, grouping and a warm-start library, were both measured against
pre-committed bars and came up short, so neither shipped.

See plans `0082` (sweep), `0083` (grouping), `0084` (coverage) for full detail.
