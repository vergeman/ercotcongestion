# 0084 - coverage-decomposition — G1 = FAIL (library not built); admission verdict PENDING

Type: feat
Branch: feat/0084-coverage-decomposition

**Outcome: gate G1 failed (+0.019 vs a +0.03 bar).** The lifetime library and
warm-start (commits 3–4) were **not built** — 0082's 240d window had already
absorbed the seasonal memory they existed to recover. The measurement redirected
the branch: the gap is **58% rejection** (`min_hours=25`) vs **16% forgetting**,
so the admission work (commit 5) became the main event. Narrative in
`plan/0084-summary.md`.

## Goal

* Re-decompose the coverage gap **at the operating point 0082 chose** — `(240, 7,
  λ=1)`, coverage 0.861 — into: warm-startable (a fit once estimated an SF for
  this key), seen-but-never-fitted, and genuinely new.
* Build the **lifetime constraint library** and a **warm-start scoring mode**: a
  scored-week constraint with no column in the current fit inherits its
  last-fitted SF instead of an implicit `SF = 0`.
* Resolve **R6** — *does closing coverage buy OOS skill?* — against bars fixed
  before the run, with a placebo arm proving any gain is constraint-specific.
* Measure and reduce **novel-constraint latency**: days from a constraint's first
  bind to its first SF column. Sweep the two admission knobs 0082 left alone
  (`min_hours`, `refit_days`).

## Context

* **R2 (0082) closed as a qualified NO** and its numbers are now stale twice
  over. It ran at `window=60`: coverage 0.814, seasonal share of novel mass 0.507
  (bound at all) / 0.303 (bound ≥25h). The chosen point is `window=240`, where
  coverage is already **0.861** — a 240d window absorbs by itself much of what a
  60d window called "seasonal memory." **The tier split must be re-measured at
  240 before any warm-start code is written.** This is the 0083 lesson (a stale
  0.468 baseline nearly bought a false win) applied one branch early.
* **`coverage_probe`'s history band collapses at `window=240`.** The band is
  `[s − lookback, s − window)`; at the defaults (`lookback=365`, `window=60`)
  that is 305 days, but at `window=240` it is **125 days** — a season, not a
  year. Every share it reports at the real operating point would be deflated by
  construction. Fix the band, not the number.
* **History is 2023-12-13 → 2026-07-01** (899k rows, 8,490 keys) — S-hist is
  effectively done. But a full-lifetime band plus a 240d window means the first
  scorable week is late; admit weeks on a `--min-history-days` floor and emit the
  band length per week rather than silently truncating.
* **The drift curve makes warm-start plausible now in a way it was not at (60,
  0.1):** `corr(SF_t, SF_{t+60d})` is 0.832 at the new point vs 0.459 at the old.
  A stale SF row is a much better guess than it used to be. That is the mechanism
  this branch tests — not an assumption it rests on.
* **R3 failed; grouping does not ship.** Everything here is keyed by the raw
  `constraint|contingency`. Do not revive grouping as a coverage lever — 0083
  measured it isn't one (constraints only merge when they co-bind *often*, so
  both members already cleared `min_hours`; the rare novel constraints that cause
  the gap correlate with nothing and stay singletons).
* RTC+B (2025-12-05) splits the scorable range roughly in half. No pooled number
  without the pre/post split visible.

## Approach

Work in `compute/sf/`. **Score-time augmentation, not a fit-time prior:** the
library injects rows into `SF` *after* the ridge, on the prediction side. It
tests "is a stale SF better than zero?" directly, at near-zero cost, without
touching `fit.py`. A ridge-toward-prior (`(XᵀX + λI)β = XᵀY + λβ₀`) is the
follow-on *if and only if* the cheap version clears.

**Commit 1 — `sweep_ibp` trim fix (prerequisite, small).**
0083's noted follow-up: the sweep trims to `--start` *after* `evaluate` returns,
so each arm scores ~98 weeks and discards ~35. Move the trim into the week loop
before this branch's long sweeps (commit 5 adds a `refit=1` arm — 7× the fits;
paying for discarded weeks on top of that is not affordable).

**Commit 2 — `coverage_probe.py` → the tier decomposition. THE GATE.**
Rework the probe to run honestly at `(240, λ=1)`:
* Replace the fixed lookback with a **lifetime-to-date** band (all history strictly
  before the fit window) plus `--min-history-days` (default 365) as the
  week-admission rule; emit `hist_days` per week so shares are interpretable.
  Keep `--lookback-days` for the fixed-band variant so 0082's 0.507/0.303 stays
  reproducible.
* Split novel μ-mass into three tiers, keyed on what the library could *actually*
  do — not on "was it ever seen":
  * **A — warm-startable:** the key cleared `min_hours` in some *earlier fit
    window*, so a fitted SF row exists to inherit.
  * **B — seen, never fitted:** bound at some point, never enough hours in any
    window. The library has nothing to inject; only `min_hours`/`refit` help
    (commit 5).
  * **C — genuinely new:** no history. Irreducible; flag honestly.
* Emit `coverage_ceiling = 1 − (mass_B + mass_C)/mass_total` — the most
  warm-start can possibly buy — and the **age distribution** of tier-A mass
  (how stale the inherited row would be).
* Pre/post-RTC+B split on every share.

**Commit 3 — gated. NOT BUILT** (G1 closed). No `library.py`, no
`ConstraintLibrary`, no `latest_sf` reader.

*Design as specified, kept for the record:*
**`library.py`, the lifetime constraint library (pure + a reader).**
* In-memory `ConstraintLibrary`, built **incrementally during the eval walk**:
  after each refit, record each kept constraint's SF row with its `as_of`
  (window_end) and binding hours. `lookup(keys, as_of)` returns rows fitted
  **strictly before** `as_of` — the no-lookahead invariant is the whole
  correctness burden of this file and gets a test that fails if it is violated.
* **Warmup matters and biases the result downward if ignored:** `eval` reads only
  `2×window` behind `--start`, so early scored weeks see a shallow library.
  Extend the read range (`--library-warmup`, default: all available history) and
  emit `library_depth_days` per week.
* No new table. The persisted library is a *query* over `implied_shift_factors`
  ("latest `window_start` per `constraint_key` ≤ as_of") — one source of truth,
  and migration 25 already indexes `(run_id, window_start)`. Add
  `latest_sf(conn, run_id, as_of)` to `persist.py`.

**Commit 4 — gated. NOT BUILT** (G1 closed). R6 was never run: with a ceiling of
+0.019 coverage, no warm-start arm could clear an R² bar, and 70% of the mass it
would inherit is >90d stale. R6 is **withdrawn, not failed** — it was never
measured, because the gate that precedes it said the measurement could not pay.

*Design as specified, kept for the record:*
**warm-start scoring + the R6 measurement.**
* `evaluate(warm_start=...)`: `"off"` (status quo) | `"last"` (inherit the
  library row) | `"placebo"`. Augment `SF` with library rows for scored-week
  constraints lacking a column, then score as usual.
* **`"placebo"` is the fair control** — inject a *different* constraint's row
  (seeded permutation of the keys), same row count, same magnitude distribution,
  zero constraint-specific information. R3 was nearly reported as a modest win
  against the wrong baseline; a coverage number that rises **by construction**
  is exactly the shape of metric that needs this.
* New columns: `coverage_ws`, `n_warm`, `warm_mass_share`, `warm_age_days`.
* Emit skill by **warm-age bucket** (≤30 / 30–90 / 90–180 / >180d) — that curve
  is what would tune a decay factor later. Do not build the decay factor now.

**Commit 5 — novel-constraint latency + the admission sweep.**
Addresses tiers B and C, which exist regardless of commit 2's verdict — so this
commit is **not** gated on it.
* Measure current latency: per newly-appearing constraint, days from first bind
  to first SF column under `(window, refit, min_hours)`. Report median/p90 — the
  handoff's design target is ~1 day and nobody has measured the actual number.
* Sweep the two axes 0082 explicitly did not: `min_hours ∈ {5,10,25} × refit ∈
  {1,3,7}` at `(240, λ=1)`, ranked on OOS with coverage and latency alongside.
  Lowering `min_hours` admits under-identified columns — the accuracy guard is
  what stops that, so it is a real sweep with a real chance of "no change."
* Cost note: `refit=1` is 7× the fits. Run the `refit ∈ {1,3}` arms on a 6-month
  scoring range and `refit=7` on the full range; do not silently compare the two
  ranges' means.

**Commit 6 — verdict, docs, gated persistence.**
Risk map (`version3-implementation-plan.md`) updated with R6 either way;
`plan/0084-summary.md` in the 0082/0083 house style. **Gated on R6 passing:**
`--warm-start` on `runner.py` and warm-started rows persisted with a provenance
flag. If R6 fails, that work is not built — the measurement is the deliverable,
and the coverage-gap decomposition still ships as writeup 8.3.

## Pre-registered bars — fixed before any run; not edited after

**Gate G1 (commit 2 → commits 3–4).** Build warm-start only if
`coverage_ceiling − coverage ≥ 0.03` at `(240, 7, λ=1)`. Below 3 points of
μ-mass the R² payoff is inside week-to-week noise, and the library is not worth
its complexity. If G1 fails: skip commits 3–4, go straight to commit 5 (which
attacks tiers B/C), and report the tier table as the branch's finding.

**R6 (commit 4).**
* *Pass (warm-start ships):* all three —
  * mean OOS pooled R² ≥ baseline **+0.01** on identical weeks;
  * on the **bottom-coverage quartile** of weeks (where collapse actually
    happens — coverage is the strongest explanator, weekly corr 0.453), OOS
    pooled R² ≥ baseline **+0.03**;
  * **placebo gain ≤ ⅓ of the warm-start gain** (the information is
    constraint-specific, not "any plausible row helps").
* *Guard (do no harm):* rank-Spearman / sign-agree / top-decile each ≥ baseline
  − 0.005; and on the **top-coverage quartile** — weeks that need no warm-start —
  OOS pooled R² ≥ baseline − 0.005. A stale row must not poison a healthy week.
* *Report either way:* coverage lift, `n_warm`/week, warm mass share, the
  skill-vs-age curve, `library_depth_days`, pre/post-RTC+B.
* *Fail is an outcome, not a retry:* warm-start does not ship; the gap's
  seasonal tier is documented as **measured but not monetizable**, which is
  itself writeup 8.3's finding and directly informs S4's cold-start design.

**Commit 5 admission point.** Adopt a new `(min_hours, refit)` only if OOS pooled
R² ≥ current − 0.005 **and** median novel-constraint latency improves ≥ 2 days.
Coverage alone does not justify a move.

**Do NOT touch:** `fit.py` ridge math (the fit-time prior is the follow-on, not
this branch) · `metric.py` / `bp = max|SF|` · served `bp_ercot` /
`implied_binding_proximity` / `api/` · frozen `legacy/` + `experiments/` ·
`grouping.py` (R3 is closed; do not re-litigate it as a coverage lever).
**Do NOT** adopt `(240, λ=1)` as code defaults — still S5. Pass them on the CLI.

## Result

**Gate G1 — FAIL.** 46 weeks, `(240, 7, λ=1)`, lifetime history band:

| tier | share of novel μ-mass |
|---|---|
| A — warm-startable (a prior fit kept it) | **0.157** |
| B — seen, never fitted (`min_hours` rejected it) | **0.580** |
| C — genuinely new | 0.263 |

Coverage **0.863** → ceiling **0.882**. Achievable lift **+0.019** vs a **+0.03**
bar. And the ceiling is optimistic: **70% of tier-A mass is >90d stale** (37% at
90–180d, 33% beyond).

**Cause — the same trap 0083 fell into, caught one branch earlier.** Tier A was
**0.250** at `window=60` and is **0.157** at `window=240`: *0082's window change
had already bought most of the seasonal memory the library was designed to
recover.* The fix was obsolete before it was written. R2's "0.507/0.303 seasonal"
was measured at the retired operating point — and at `(60, 365)` this probe still
reproduces it **exactly**, so the rework reinterprets R2 rather than replacing it.
(Note tier A ≠ R2's `seen_material`: 0.250 vs 0.303 at the *same* settings. The
operational bar is "a real fit window kept it," not "it bound ≥25h somewhere in a
lookback band.")

**The redirect — the bar is the bug.** Tier B is **3.7× tier A**. These
constraints are not forgotten, they are **rejected** by `min_hours=25`. Measuring
the two admission knobs (no ridge fits needed):

| refit | min_hours | median latency | p90 | blind μ-mass | admit rate | coverage |
|---|---|---|---|---|---|---|
| **7** | **25** *(today)* | **23.5 d** | 192 d | **0.105** | **0.208** | **0.863** |
| 7 | 5 | 6.5 d | 99 d | 0.062 | 0.542 | 0.926 |
| 1 | 5 | 2.4 d | 97 d | 0.036 | 0.545 | **0.956** |

**The handoff's design target was ~1 day; the measured median is 23.5 days**, and
**only 21% of new constraints ever receive a column at all.** `min_hours` drives
coverage; `refit` sets the latency floor. Together: 0.863 → **0.956** coverage —
**5× the +0.019 a perfect library could have bought.**

**Accuracy guard — first read (8 weeks, identical weeks both arms, post-RTC+B):**

| | mh=25 | mh=5 | Δ |
|---|---|---|---|
| OOS pooled R² | 0.812 | 0.835 | **+0.023** |
| rank-Spearman | 0.823 | 0.847 | **+0.024** |
| sign-agree | 0.940 | 0.948 | +0.008 |
| top-decile | 0.788 | 0.798 | +0.010 |
| coverage | 0.897 | 0.957 | **+0.060** |
| sf_stability | 0.553 | 0.599 | **+0.047** |
| n_kept | 1,097 | 2,340 | +1,244 |

Nothing traded — every metric improves, stability included. `min_hours=25` was
discarding ~1,240 identifiable columns per window and paying for it. Same species
as 0082's decorative λ: a knob never selected against anything.

**NOT YET A VERDICT — `min_hours` is not adopted.** Those 8 weeks are all
post-RTC+B, and RTC+B is where this project keeps finding regime breaks. The
46-week confirmation spanning both sides is running (`ibp_sweep_admission.csv`).
The bar does not move until it lands.

**Perf (incidental but load-bearing).** The first admission grid **did not
finish** (killed at 26 min): each boundary sliced a ~140MB float frame out of the
panel purely to compute *integer* binding counts. `_BindCounts` (daily cumulative
counts) makes it exact-and-O(1) — **26min+ → 25s**, numbers bit-identical.

## Acceptance

* [x] `sweep_ibp` trims to `--start` inside the week loop — **bit-exact**
      (`DataFrame.equals`) at **3.27×** (52 weeks fitted → 17, 494s → 151s).
      Caveat recorded: grouped arms' `group_churn` is NaN on the first scored
      week (it previously compared against a discarded warmup week); dead path
      since R3 failed.
* [x] `coverage_probe` runs at `(240, 7, λ=1)` with a lifetime history band,
      emits `hist_days`, and reproduces 0082's 0.507/0.303 **exactly** at
      `(60, lookback=365)` — including both RTC+B arms.
* [x] Tier table (A/B/C + `coverage_ceiling` + tier-A age distribution) recorded,
      pre/post-RTC+B visible. **G1 verdict recorded BEFORE commits 3–4 were
      written** — they were not written.
* [x] ~~`ConstraintLibrary.lookup(as_of)` no-lookahead test~~ — **N/A, gate
      closed.** The equivalent lookahead risk *was* tested where it survived: a
      constraint whose first bind is in the scored week must land in tier C, not
      tier B (an `ever_seen` built from the whole panel would inflate the
      library's reachable mass).
* [x] ~~`warm_start="off"` bit-exact no-op~~ — **N/A, gate closed.**
* [x] ~~R6 verdict~~ — **withdrawn, not failed.** Never measured: G1 says the
      measurement cannot pay.
* [x] Novel-constraint latency measured (median 23.5d / p90 192d at the current
      point); `admission_grid.csv` committed; the cheap grid carries no accuracy
      claim by construction — the guard comes from `sweep_ibp`.
* [ ] **PENDING** — 46-week `min_hours ∈ {5,10,25}` guard sweep at `(240, 7, λ=1)`,
      pre/post-RTC+B split. Adopt `min_hours` only if OOS R² ≥ current − 0.005
      **and** median latency improves ≥ 2 days. Coverage alone does not justify a
      move.
* [x] Gated work honored: no library, no warm-start, no migration, no runner
      flag. **Bars not moved.**
* [x] 48 tests green (37 existing + 11 new).

## Follow-ups (not blocking)

* **`refit=1` is unguarded.** The cheap grid says it takes latency 6.5d → 2.4d,
  but no OOS arm was run for it (7× the fits). Guard it before adopting.
* **Adoption belongs to S5**, with `(240, λ=1)`. Do not change `fit.py` defaults
  here.
* **RTC+B, third sighting.** Coverage is materially better post-cutover (0.875 vs
  0.841) and tier A is 2.7× larger (0.209 vs 0.078). With 0083's ~2× disjoint
  stability jump, that is now two independent post-RTC+B signals — feeds
  handoff §5.5 item 1.
