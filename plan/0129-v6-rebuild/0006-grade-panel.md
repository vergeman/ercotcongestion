# 0129-0006 - grade-panel

Type: feat
Branch: feat/0129-0006-grade-panel
Depends on: `0002`, `0003`, `0004`, `0005`

## Goal

* Replace the three grade cells — which currently count join membership — with real Σμ
  scoring, forecast against settled.
* Score constraints and nodes as separate halves, never as one blended number.
* Show a persistence baseline beside the model's score.

## Context

* Current state per the prototype's data-status table: `partial` — *"the three grade
  cells still count join membership; the miss decomposition under them is real Σμ,
  forecast against settled."* Counting membership answers "was it on both lists", which
  is not the same question as "was the forecast any good".
* Depends on `0002` (window layer), `0004` (forecast history) and `0005` (below-floor
  μ). Without `0005` in particular, the score is computed over the 33 cast constraints
  and inherits the truncation as if it were model error.
* **Three traps, all previously hit:**
  * *The universe trap* — scoring only what was forecast makes a forecast that predicts
    one constraint and gets it right look perfect. The universe must be the union of
    forecast and settled sets.
  * *The base-rate trap* — on a grid where a handful of elements bind almost daily, a
    hit-rate is mostly measuring the base rate. Report against a baseline, not in
    isolation.
  * *Signed errors netting out* — a headline reading "balanced" while both halves are
    badly low. `0003` measured signed node errors netting to −0.16. Do not average
    the constraint and node halves.
* **Persistence beats the model.** Repeating yesterday has scored better than the
  forecast on all three axes. A grade panel that omits it is flattering the model, and
  "× random" is not an adequate reference on its own.

## Approach

* Work in: `compute/analysis/`, `api/analysis.py`
* Three metrics, kept separate and separately labelled, following
  `docs/daily_brief_v6_prototype.html`: **detection** (expected-tie average precision
  over the forecast rank), **magnitude** (soft overlap of the daily Σμ vectors), and
  **timing** (the same AP over pooled constraint-hours, chance-adjusted before it is
  compared with daily detection).
* Universe = union of forecast-set and settled-set, so a no-show costs detection and a
  surprise costs it too. Settled zeros print as `$0`, never a dash — "it did not bind"
  must never read as "we do not know".
* Use **absolute** or squared error for magnitude. If a signed bias number is shown, show
  it as its own figure with its own label, never folded into an accuracy score.
* Render the persistence baseline (yesterday repeated) beside every metric, on the same
  scale. If the model loses, the panel says so.
* Constraints and nodes are two rows, not one score. The node row stays struck through
  and labelled "not graded" until `0003` lands (`NODES_GRADEABLE`).
  Nodes do not bind: their detection and timing labels use `abs(congestion) > 1e-6`
  $/MWh only to discard floating-point residue, not a materiality floor. Node magnitude
  always uses the full `abs(SPP − system_lambda)` profile, so opposite signed errors
  cannot net out.
* Do NOT touch: the modelling path, or the scoreboard tables (`scoreboard_daily` /
  `scoreboard_weekly`) — this is the per-day panel, not the running scoreboard.

## Acceptance

* [ ] All three cells derive from Σμ over the union universe; none counts list membership.
* [ ] A synthetic case — forecast one constraint, get it exactly right, miss ten that bound — scores poorly on detection. (Under the old cells it scored perfectly.)
* [ ] A persistence baseline renders beside every metric, and the panel is legible when persistence wins.
* [ ] Constraint and node halves are separately visible; no averaged number exists anywhere in the response.
* [ ] Signed bias, if shown, is labelled as bias and is not an input to any accuracy figure.
* [ ] Settled non-binding renders `$0`, not `—`.
* [ ] Node detection/timing use the `1e-6` $/MWh numerical-noise epsilon, not an
  economic materiality threshold; node magnitude includes all absolute congestion.
