# 0083 - collinear-grouping

Type: feat
Branch: feat/0083-collinear-grouping

## Goal

* Correlation-cluster co-binding μ columns within each fit window into composite
  constraint-group keys; fit SF on the aggregated group panel.
* Emit the head-to-head measurement that resolves **R3**: does grouping raise
  cross-window SF stability without costing OOS accuracy?
* Gated on that verdict: re-key SF persistence to groups and persist group
  membership, unblocking signed per-group claims and the node explorer.

## Context

* Co-binding constraints are collinear within a window; the ridge's within-block
  allocation is arbitrary and flips between refits. Every signed, named claim
  (node explorer, error attribution) is blocked until the fit's unit is a group
  (`handoff §4/§5.2`, `pivot §4.2`).
* **The pass criterion in both design docs is stale.** "Stability rises from
  0.468" was measured at `(window=60, λ=0.1)` — the point 0082/S1.5 retired.
  At the chosen `(240, 7, 1.0)` the baseline is different (drift@60d 0.459→0.832).
  S2 re-measures the ungrouped baseline at the new point and compares against
  *that*. Do not carry 0.468 forward.
* **`sf_decay`'s Δ grid tops out at 60d against a 240d window** — those fits
  overlap 75%, so the curve measures overlap, not drift. A genuinely disjoint
  pair needs Δ = window_days. `sf_decay` already takes `deltas_days`; the CLI
  hardcodes `(7,14,30,60)`. Expose it.
* Predicted side-effect worth testing: a group is kept when its *aggregate*
  binds ≥ `min_hours`, so rare constraints co-binding with a common one stop
  being dropped. **Grouping should lift coverage** — a second, independent lever
  on the R2 gap that warm-start only half-closes.
* RTC+B cutover (2025-12-05): never report a pooled number over windows
  straddling it without the pre/post split visible.

## Approach

Work in `compute/sf/`. Four commits; commit 4 is gated on commit 3's verdict.

**The fit change is aggregate-then-fit, not average-after-fit.** Under perfect
collinearity only the mass-weighted sum `Σ_c a_c·SF[c,sp]` is identifiable, so we
form the group column `m_g[h] = Σ_{c∈g} μ[h,c]` and solve for `SF_g` directly.
Averaging per-constraint SFs post-hoc leaves the arbitrary allocation in the fit
and fixes nothing.

### Commit 1 — `sf/grouping.py`: the grouping primitive (pure, no I/O)

* `group_constraints(M_window, rho_min, linkage="complete") -> pd.Series`
  (constraint_key → group_key). Hierarchical clustering on `1 − corr` over the
  window's μ columns (zeros included — they are real observations and they are
  what conditions `XᵀX`), cut with `fcluster(criterion="distance")` so every
  pair inside a group has `corr ≥ rho_min`. Merge on positive correlation only.
* `aggregate_mu(M_window, labels) -> pd.DataFrame` — (hours × groups), μ-mass sum.
* `group_members(M_window, labels) -> pd.DataFrame` — `(group_key, constraint_key,
  mu_mass_share)`, for persistence and the explorer.
* **Group key = the dominant member's `constraint_key`** (highest in-window μ-mass).
  Readable, and a singleton group keys to itself — so `rho_min=1.0` is a
  bit-for-bit no-op and the existing schema stays backward compatible.
* Write fresh. Do NOT import `compute/legacy/clustering/` — it clusters buses,
  it is frozen, and 0082 set the precedent of keeping the kept→frozen edge cut.
* Verify on a synthetic panel: three planted blocks recovered; a perfectly
  collinear pair merges at any `rho_min ≤ 1`; independent columns never merge.

### Commit 2 — thread grouping through the fit + eval paths

* Add an optional `rho_min: float | None` to `rolling.rolling_bp` and
  `eval.evaluate`. When set, map `M → M_g` **before** calling the fit; when
  `None`, behavior is byte-identical to today. `fit.implied_shift_factors` stays
  untouched — the ridge stays pure, grouping threads through the caller the way
  `standardize` does.
* `eval.evaluate` additionally emits, per scored week:
  * `n_groups` / `n_constraints` (compression ratio)
  * `group_churn` — membership Jaccard vs the previous window's matched group.
    Dominant-member keying churns if two members swap mass rank; this measures it.
  * `sf_stability_proj` — **the fair drift control**: the ungrouped SF projected
    onto the same groups (μ-mass-weighted member average). Comparing a 150-row
    grouped SF against a 400-row ungrouped SF on raw correlation is not
    apples-to-apples; projecting the baseline into the group row-space is.
* Expose `--deltas` on the `eval` CLI so `sf_decay` can run out to Δ = window.
* **Null-op check:** `--rho-min 1.0` reproduces the ungrouped metrics exactly.
  This is the proof the wiring is inert when it should be.

### Commit 3 — the R3 measurement (no product code; CSVs + findings)

* Extend `sweep_ibp.py` with a `--rho-min` axis (reuses its one-time panel load
  and OOS ranking; do not fork a parallel sweep script). Sweep
  `rho_min ∈ {0.5,0.6,0.7,0.8,0.9,0.95,1.0}` at fixed `(240, 7, λ=1.0,
  std_floor=100, min_hours=25)` over ≥18mo — find the accuracy/stability knee.
* Head-to-head at the knee: `eval --emit-decay --deltas 7,14,30,60,240` for the
  grouped and ungrouped arms. Pre/post-RTC+B split reported separately.
* **Pre-registered bars (fixed before results — do not edit post-hoc):**
  * *Pass (stability):* disjoint drift (Δ=240d) and `sf_stability` rise by
    ≥ +0.10 absolute vs `sf_stability_proj`, the projected control.
  * *Guard (accuracy):* rank-Spearman, sign-agree, top-decile each ≥ baseline
    − 0.01; OOS pooled R² ≥ baseline − 0.02. Grouping may not buy stability by
    quietly destroying locality.
  * *Report either way:* n_groups, coverage delta, group_churn.
* Commit the sweep CSVs as evidence (`ibp_sweep_grouping.csv`), per the 0082
  precedent. Write `plan/0083-summary.md`; mark **R3** in
  `plan/version3-implementation-plan.md`.
* **Fail branch is a real outcome, not a retry:** if the guard trips, grouping
  does not ship as the fit unit; `bp = max|SF|` survives untouched (a max over a
  block is already stable), signed per-group claims stay blocked, and we say so.
  If `group_churn` is material but stability passes, add Jaccard-matched
  carry-forward group IDs before commit 4 — not a re-run of the bars.

### Commit 4 — GATED on commit 3: re-key persistence to groups

* Migration `26_sf_constraint_groups.sql`: new
  `sf_constraint_groups(run_id, window_start, group_key, constraint_key,
  mu_mass_share)`; add `n_groups`, `rho_min` to `sf_window_meta`.
  `implied_shift_factors.constraint_key` needs **no migration** — migration 25
  left it free-form TEXT for exactly this.
* `runner.py`: `--rho-min` writes group keys into `implied_shift_factors` and
  membership into `sf_constraint_groups`, inside the existing `on_refit`
  transaction. `persist.py` gets `copy_group_rows`.
* Verify: row count drops ~an order; membership expands back to the full
  constraint set with mass shares summing to 1 per group; the ungrouped path
  (no `--rho-min`) is unchanged.

**Do NOT touch:** `fit.py` ridge math · `metric.py` · the served `bp_ercot` /
`implied_binding_proximity` path · `api/` · frozen `legacy/` + `experiments/`.
**Do NOT** adopt `(240, 1.0)` as code defaults — that is S5 (0082 follow-up);
S2 reaches the operating point via CLI flags only.

## Acceptance

* [ ] `grouping.py` recovers planted blocks on a synthetic panel; merges a
      perfectly collinear pair; never merges independent columns.
* [ ] `--rho-min 1.0` reproduces ungrouped `evaluate` metrics exactly (null-op).
* [ ] `eval --deltas` reaches Δ = window_days; the disjoint (Δ=240d) drift number
      exists for both arms.
* [ ] `evaluate` emits `n_groups`, `n_constraints`, `group_churn`,
      `sf_stability_proj`.
* [ ] Ungrouped baseline **re-measured at (240, 7, 1.0)** — 0.468 not carried
      forward.
* [ ] rho_min sweep CSV committed; knee identified.
* [ ] R3 verdict recorded against the pre-registered bars, pre/post-RTC+B split
      visible, and `version3-implementation-plan.md` risk map updated — **pass or
      fail**.
* [ ] (If pass) migration 26 applies + idempotent; `--rho-min` persists group SF
      + membership; mass shares sum to 1 per group; ungrouped path unaffected.
