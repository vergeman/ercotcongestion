# 0083 - collinear-grouping — DONE (R3 = FAIL; grouping does not ship)

Type: feat
Branch: feat/0083-collinear-grouping

## Goal

* Correlation-cluster co-binding μ columns per fit window into constraint-group
  keys; fit SF on the aggregated group panel.
* Resolve **R3**: does grouping raise cross-window SF stability without costing
  OOS accuracy?
* *Gated on that verdict:* re-key SF persistence to groups, unblocking signed
  per-group claims and the node explorer.

**Outcome: R3 failed (+0.006 vs a +0.10 bar).** Grouping is not the fit unit; the
gated persistence work was not built. Narrative in `plan/0083-summary.md`.

## Context

* Co-binding constraints are collinear within a window; the ridge's within-block
  allocation is arbitrary and flips between refits. Every signed, named claim
  is blocked until the fit's unit is a group (`handoff §5.2`, `pivot §4.2`).
* **The docs' pass criterion was stale.** "Stability rises from 0.468" came from
  `(60, λ=0.1)`, which 0082/S1.5 retired. Re-measure the ungrouped baseline at
  the chosen `(240, 7, 1.0)` and compare against *that*.
* **`sf_decay`'s Δ grid topped out at 60d against a 240d window** — those fits
  overlap 75%, so it measured overlap, not drift. Δ must reach `window_days`.
* ~~Grouping lifts coverage (a group is kept when its *aggregate* clears
  `min_hours`).~~ **Measured false.** Constraints only merge when they co-bind
  often, so both members already cleared the bar. Not a lever on the R2 gap.
* RTC+B (2025-12-05): no pooled number over windows straddling it without the
  pre/post split visible.

## Approach

Work in `compute/sf/`. **Aggregate-then-fit, not average-after-fit:** under
collinearity only the mass-weighted sum `Σ_c a_c·SF[c,sp]` is identifiable, so
form `m_g[h] = Σ_{c∈g} μ[h,c]` and solve for `SF_g` directly. Averaging
per-constraint SFs post-hoc leaves the arbitrary allocation inside the fit.

**Commit 1 — `sf/grouping.py`, the primitive (pure, no I/O).**
Two-stage: `constraint_linkage(M)` builds the tree once per window (the
correlation and tree don't depend on `rho_min` — only the cut does, and the
sweep varies the cut); `cut_groups(link, rho)` is cheap per threshold. Complete
linkage on `1 − corr`, so the cut guarantees *every pair* in a group clears
`rho_min`, and only positive correlations merge. Group key = dominant member by
μ-mass, so a singleton keys to itself and `rho_min=1.0` is an exact no-op.
Written fresh — do NOT import frozen `legacy/clustering/`.

**Commit 2 — thread through `rolling` / `eval`.**
Optional `rho_min` maps `M → M_g` *before* the fit; `fit.py` untouched.
`RefitWindow` gains `M_fit` (its columns are what `SF`'s rows are keyed by) and
`labels`. `evaluate` also emits `n_groups`, `group_churn`, and
`sf_stability_proj` — **the fair control**: the ungrouped SF projected into the
group row-space. Correlating a ~950-row grouped SF against a ~1,020-row ungrouped
one would credit grouping for merely being a smaller, better-conditioned matrix.

**Commit 3 — the R3 measurement.** `sweep_ibp --rho-min` (with `none` sweeping
the baseline in the same pass, on identical weeks and panels) → `r3_verdict.py`.

**Pre-registered bars (fixed before results; not edited after):**
* *Pass:* `sf_stability` rises ≥ **+0.10** over `sf_stability_proj`.
* *Guard:* rank-Spearman / sign-agree / top-decile each ≥ baseline − 0.01;
  OOS pooled R² ≥ baseline − 0.02.
* *Report either way:* n_groups, coverage delta, group_churn, pre/post-RTC+B.
* *Fail branch is an outcome, not a retry:* grouping does not ship;
  `bp = max|SF|` survives untouched; signed per-group claims stay blocked.

**Commit 4 — gated. NOT BUILT** (gate closed). No migration 26, no
`sf_constraint_groups`, no `--rho-min` on the runner; `implied_shift_factors`
stays keyed by `constraint|contingency`.

**Do NOT touch:** `fit.py` ridge math · `metric.py` · served `bp_ercot` /
`implied_binding_proximity` · `api/` · frozen `legacy/` + `experiments/`.
**Do NOT** adopt `(240, 1.0)` as code defaults — that is S5.

## Result

63 weeks, `(240, 7, λ=1.0)`:

| rho_min | compression | stability | control | delta | guard |
|---|---|---|---|---|---|
| 0.7 | 1.18× | 0.413 | 0.408 | +0.005 | pass |
| 0.8 | 1.13× | 0.409 | 0.406 | +0.003 | pass |
| 0.9 | 1.09× | 0.403 | 0.397 | **+0.006** | pass |

**Cause:** ERCOT's co-binding blocks are too small for the fix to bite —
compression 1.09–1.18×, blocks mostly one element under several contingency
labels (`1661__A|DZORLIM5` + `1661__A|SGILLIM5`). Merging them is correct but
irrelevant: the map drifts because the congestion **regime rotates**, not because
credit flip-flops within blocks. Nobody had checked block size before prescribing
the fix. Guard passes everywhere — grouping is free, it just buys nothing.
Churn 0.996–0.999, so dominant-member keying was never the problem.

**Unplanned finding:** disjoint stability is ~2× higher post-RTC+B (0.49, 30
weeks) than pre (0.23, 33 weeks), in every arm including controls. Post-cutover
windows still straddle the cutover — suggestive, not clean, but worth a clean
split (handoff §5.5 item 1).

**Follow-up (not blocking):** `sweep_ibp` trims to `--start` *after* `evaluate`
returns, so each arm scores 98 weeks and discards ~35. Move the trim into the
week loop before the next long sweep.

## Acceptance

* [x] `grouping.py` recovers planted blocks; merges an exactly-collinear pair;
      never merges independent or degenerate columns. Tree built once per window
      (0.2s vs 30s), and holding out window-inactive columns is label-identical.
* [x] `--rho-min 1.0` reproduces ungrouped `evaluate` metrics **bit-exactly** on
      real panels — not merely within tolerance. (Caught a real bug: identity
      labels round-tripping through groupby-sum changed BLAS reduction order,
      moving the ridge by ~3e-13 and reordering ties in `topdecile_hit`.)
* [x] `eval --deltas` reaches Δ ≥ window_days; disjoint drift measured.
* [x] `evaluate` emits `n_groups`, `n_constraints`, `group_churn`,
      `sf_stability_proj` — `n_constraints` defined identically in both arms.
* [x] Ungrouped baseline re-measured at `(240, 7, 1.0)`; 0.468 not carried forward.
* [x] Sweep CSVs committed (`ibp_sweep_grouping{,_weekly}.csv`). No knee exists —
      the gain is flat and ~0 across the range.
* [x] R3 verdict recorded against the pre-registered bars (**FAIL: +0.006 vs
      +0.10**), pre/post-RTC+B split visible, risk map updated.
* [x] Gate honored: group persistence not built. Bar not moved.
* [x] 37 tests green.
