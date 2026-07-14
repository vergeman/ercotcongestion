# 0085 - mu-model-v1 (the forecast)

Type: feat
Branch: feat/0085-mu-model

## Goal

* Forecast, per constraint and hour: **`P(bind | covariates)`** and
  **`E[μ | bind]`** — the two heads that turn the SF map into a forward-looking
  product rather than a retrospective one.
* Propagate sampled binding sets through the SF map (`congestion = −Σ SF·μ̂`) to
  **nodal congestion with P10/P50/P90 bands**.
* Resolve **R5** — *does a covariate model beat persistence in the screening
  currency?* — against the pre-registered gate (handoff §5.5), with climatology,
  persistence and null measured **in the same harness, on the same weeks**.
* Resolve **R4** first, as a spike: can outaged elements be joined to anonymous
  constraint keys at all? Gate the outage covariate on the answer.

## Context

* **This is where the skill actually lives.** Oracle μ (realized) scores
  0.746/0.835/0.907/0.780; climatology 0.235/0.511; persistence 0.173/0.581. The
  spatial map is nearly a solved problem; **μ-forecasting is the open one.** The
  skill-decomposition finding is a contribution regardless of the gate outcome.
* **No-lose structure.** `persistence · SF` already clears the screening bar
  (top-decile 0.649 vs 0.10 chance). A screener ships even if R5 fails; R5
  decides *forecast product vs screening tool*, not *product vs nothing*.
* **Grouping is dead (R3, 0083).** The heads are **per constraint**, not per
  group. `bp = max|SF|` survives; signed per-constraint claims remain blocked by
  collinearity — that is an identifiability problem this branch does **not**
  attempt to solve and must not quietly assume away.
* **The constraint set is not settled (0084).** The pending `min_hours` guard
  sweep decides whether the map carries ~1,100 columns (`min_hours=25`) or ~2,340
  (`min_hours=5`). The 1,240 extra are precisely the **thin binders** — the
  hardest possible bind-probabilities to estimate. **Design for both**: constraint
  count is a config, never a structural assumption.
* **Three branches running, three stale baselines caught.** 0083 nearly reported
  a win against a retired operating point; 0084's whole premise evaporated
  against one. **The handoff's baseline numbers (persistence 0.581/0.771/0.649)
  were measured at `(60, λ=0.1)` and are provisional.** Re-measure every baseline
  at the adopted operating point, on identical weeks, in this branch's harness.
  Re-measuring a *baseline* is not moving a *bar* — the §5.5 bars are absolute
  and stay fixed.
* RTC+B (2025-12-05) now has **two independent signals** (0083: ~2× disjoint
  stability; 0084: coverage 0.875 post vs 0.841 pre). Treat pre/post as
  potentially structural in every pooled number; never fit across it unflagged.

## Approach

Work in `compute/mu/` (new package, sibling to `compute/sf/`). Reuse — do not
re-implement — the honest-window discipline and metric fns from
`compute/sf/eval.py`.

**Commit 1 — R4 spike: can outages be joined to constraint keys? (cheap, first.)**
The handoff calls outage flags the highest-value covariate; the implementation
plan calls the join the single most uncertain thing in S4. Settle it before
scoping any outage work.
* The under-noted bridge: shadow-price rows **already carry
  `from_station` / `to_station` / `kV`** (`loaders.py:455`) — constraint keys are
  opaque strings, but the rows behind them are not.
* Measure: what fraction of constraint keys resolve to a station pair? Do outage
  records name those same stations? Emit a match rate and a hand-audited sample.
* **Decision, pre-registered:** ≥60% of binding μ-mass joinable → build the named
  outage covariate. 30–60% → build it, flagged, for the joinable subset only.
  <30% → **outage covariate degrades to the zonal aggregate already ingested**
  (`outages_zonal`), the anticipatory-alert story weakens, and S4 proceeds without
  it. Do not let a failed join silently become a modeling project.

**Commit 2 — `features.py`: the covariate panel.**
Hourly frame, assembled from existing ingest only: `load_forecast_zonal`
(NP3-561), regional wind/solar forecasts (NP4-742/745), derived **net load**,
calendar (hour/dow/month/holiday), `regimes/binners.py` labels, and **recent
binding history per constraint** (binds in last 24h/7d/28d, hours-since-last-bind,
same-month-last-year rate).
* **Every feature must be knowable at DAM close.** Use *forecast* load and
  wind/solar, never actuals — the single easiest way to fabricate skill here is a
  lookahead feature, and this project has already caught itself once (0082's
  0.986). One test asserts no feature column reads a timestamp ≥ the prediction
  time.

**Commit 3 — `mu_model.py`: the two heads.**
* **Pooled, not per-constraint.** One model over all constraints with **constraint
  identity as a feature** (target-encoded binding rate + its own history), not
  N separate GBMs. A per-constraint GBM for something that binds 5 hours in 240
  days is hopeless — and if `min_hours=5` is adopted, ~1,240 of the columns are
  exactly that. Pooling borrows strength across constraints and is robust to
  either operating point.
* Head 1: `P(bind at h)` — gradient-boosted classifier. Report **calibration**
  (reliability curve, Brier), not just AUC: the bands downstream are only as
  honest as the probabilities feeding them.
* Head 2: `E[μ | bind]` — net-load-bucketed conditional climatology first
  (the measured magnitude backbone), quantile regression only if the simple
  version is beaten.
* **Honest walk-forward, same discipline as `sf/eval.py`:** train on the trailing
  window ending strictly before the scored week. No exceptions, no "just for the
  sweep."

**Commit 4 — baselines + the scoring harness.**
All four μ sources scored **in one harness, on identical weeks**: model,
climatology, persistence(24h), null — plus **oracle μ as the ceiling** (it
isolates the map's contribution from the forecast's).
* Two currencies, always reported together (handoff §7): **magnitude** (pooled
  R², MAE) and **screening** (rank-Spearman, sign-agree ±$1 deadband, top-decile
  hit). Leading with magnitude would make a working screener read as a failing
  forecast.
* Splits: per-regime (existing binners) and **pre/post-RTC+B**.

**Commit 5 — propagate to nodal congestion + R5 verdict.**
Sample binding sets from head 1, draw μ from head 2, push through the SF map →
per-node P10/P50/P90. Score against the pre-registered gate.
* Coverage is reported **alongside** skill every week — 0084 measured the blind
  spot at 10–14% of μ-mass; hiding it would misattribute forecast misses to the
  model.

**Commit 6 — docs, `0085-summary.md`, risk map (R4/R5 recorded either way).**

**Do NOT touch:** `compute/sf/fit.py` ridge math · `metric.py` / `bp = max|SF|` ·
served `bp_ercot` / `api/` · frozen `legacy/` + `experiments/` ·
`grouping.py` (R3 closed). **Do NOT** adopt operating-point defaults here — that
is S5. **Do NOT** build product surfaces (§6) in this branch.

## Pre-registered bars — fixed before any run; not edited after

**The §5.5 gate, verbatim. Either bar clears a row:**

| outcome | magnitude bar | screening bar |
|---|---|---|
| Forecast product | pooled R² ≥ 0.5 | Spearman ≥ 0.70 **and** sign ≥ 0.85 |
| Screening tool | R² 0.3–0.5 | Spearman 0.60–0.70, top-decile ≥ 0.60 |
| Forecast is not the product | R² < 0.3 | Spearman < 0.60 **and** top-decile ≤ 0.649 |

**R5 existence test:** the covariate model must beat **persistence, re-measured
on identical weeks at the adopted operating point**, in the screening currency.
The handoff's 0.581/0.771/0.649 are from the retired `(60, λ=0.1)` point and are
**not** the comparison — recomputing them correctly is not moving the bar.

**R4 bar:** as in commit 1 (≥60% joinable μ-mass → build; <30% → zonal fallback).

**Report either way:** calibration of head 1, oracle-vs-model gap (where the skill
is missing), coverage alongside skill, per-regime and pre/post-RTC+B splits.

**Fail is an outcome:** if R5 fails, the screener ships on `persistence · SF` and
the skill-decomposition finding (oracle 0.746 vs naive ~0.20) stands on its own.

## Acceptance

* [ ] **R4 spike** recorded: constraint-key → station match rate, joinable μ-mass
      share, hand-audited sample, decision against the pre-registered bar.
* [ ] No feature reads data unavailable at DAM close — asserted by a test that
      fails on a deliberately leaked actual.
* [ ] Heads trained walk-forward on trailing windows ending strictly before each
      scored week; a run at the `sf/eval.py` window convention reproduces its
      week boundaries.
* [ ] Head 1 calibration reported (reliability curve + Brier), not only AUC.
* [ ] Model, climatology, persistence, null **and oracle** scored in one harness
      on identical weeks; both currencies; per-regime and pre/post-RTC+B splits.
* [ ] Nodal P10/P50/P90 emitted; empirical coverage of the bands reported (a P90
      that isn't hit 10% of the time is not a P90).
* [ ] **R5 verdict recorded against the §5.5 gate**, with the re-measured
      persistence baseline printed beside it.
* [ ] Runs at both `min_hours` operating points, or explicitly states which one it
      assumes and why.
* [ ] Tests green.
