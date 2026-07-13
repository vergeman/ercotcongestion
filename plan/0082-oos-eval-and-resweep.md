# 0082 oos-eval-and-resweep

Type: feat
Branch: feat/0082-oos-eval-and-resweep

## Goal

* Make the honest out-of-window fit (`window_end = refit_start`) a first-class mode, not an experiment — one reusable per-refit metric pass that both the sweep and `sf_window_meta` call.
* Retire **R1** (does the operating point move under honest selection?) by re-pointing `sweep_ibp.py` at OOS metrics and re-sweeping.
* Retire **R2** (is the 19% coverage gap mostly seasonal memory?) with one query against the now-extended history — do this first, it's the cheapest decisive probe.

## Context

* Today's `fit_r2 ≈ 0.986` is **in-sample** (lookahead window). Honest OOS with oracle μ is **0.746**; disjoint-window SF stability is **0.468**, not the 0.90 the doc implies. Numbers from `experiments/ibp_out_of_window/` (README).
* Those four scripts already import the production fit unmodified — they re-walk refits and re-fit per script. S1 consolidates their logic into one `sf/eval.py` so the sweep objective, the `sf_window_meta` backfill, and ad-hoc runs share it.
* `sweep_ibp.py` selects on `bp_max` / in-sample `mean_r2` (a DOF curve) — cosmetics. Until it selects on OOS metrics, the operating point is provisional and nothing expensive should be designed on it.
* S0b left `sf_window_meta.oos_r2` / `coverage` NULL for exactly this section.
* NP4-191 history now spans 2023-12-13 → 2026-07-01 (backfill complete), enabling the R2 probe.

## Approach

Work in: `compute/sf/` (new `eval.py`, edits to `sweep_ibp.py`). Reuse the honest-window logic and μ sources from `experiments/ibp_out_of_window/common.py` and the metric fns (`row_spearman`, `sign_agreement`, `topdecile_hit`, coverage) from `screening_and_coverage.py`.

**S1.1 — R2 coverage probe (do first).** New `sf/coverage_probe.py`. Per scored week, split the *novel* μ-mass (constraints binding in the week but absent from the trailing 60d fit) into:
- **seasonal memory** — the constraint appeared in `[week−365d, week−60d]`,
- **genuinely new** — never seen in available history.
Report the seasonal-memory share of novel mass. **Pass criterion: ≥60% seasonal ⇒ warm-start the fit with historical constraints closes most of the gap, no new modeling.** One pass over 2024→2026. Effort: S.

**S1.2 — `sf/eval.py`: one honest-window metric pass.** Single `evaluate(M, C, window_days, refit_days, …) -> DataFrame`, one row per refit, emitting: honest OOS pooled R², cross-node rank-Spearman, sign-agree (±$1), top-decile hit, coverage, and disjoint-window SF stability — plus the in-sample R² for side-by-side. Lift, don't reinvent: import the honest window + μ sources from `common.py`, the metric fns from `screening_and_coverage.py`. CLI mirrors the harness scripts; writes a per-run CSV. Effort: M.

**S1.3 — Backfill `sf_window_meta.oos_r2` / `coverage`.** Add `--persist-eval` (to `eval.py` or `runner.py`) that `UPDATE sf_window_meta SET oos_r2, coverage … WHERE run_id=%s AND score_start=%s`. Match on `score_start` (unique per refit): the honest fit's window differs from the persisted lookahead window, but both describe the same scored week. Effort: S.

**S1.4 — Re-point `sweep_ibp.py`.** Swap the objective from `bp_max` to the S1.2 OOS metrics (read them, not the in-sample diagnostics JSON). Extend the grid: `window ∈ {60,120,240,365}`, `refit ∈ {1,7,14}`, `λ` into its effective range (current 0.1 vs XᵀX diag ≈1440). Emit the decay curve `corr(SF_t, SF_{t+Δ})`, Δ ∈ {7,14,30,60}. Effort: M.

**S1.5 — Re-sweep + record the operating point (retires R1).** Run the extended sweep on the full history, pick the config that maximizes the OOS screening metrics, and write the chosen defaults + the before/after table into this doc. ~1 day compute. Effort: M.

Do NOT change `fit.py` / `rolling.py` fit math, or the served `bp_ercot` / `implied_binding_proximity` path. The `experiments/ibp_out_of_window/` scripts stay as-is (frozen reference); `eval.py` supersedes them for production.

## Acceptance

* [x] **S1.1** — `sf/coverage_probe.py`, 81 weeks, full 365d lookback. **R2 = qualified NO.** Mean coverage 0.814 (reproduces the ~19% gap). Seasonal share of novel mass: **0.507** (bound at all in prior year) / **0.303** (bound ≥25h, fit-eligible). ⇒ Warm-start recovers only ~30–50% of the gap; the rest (shoulder-season novel constraints — 2025-09-18, 2026-04-09/23) needs shorter refit cadence, not a free lunch. Do NOT budget the coverage gap as a warm-start win.
* [ ] **S1.2** — `python -m compute.sf.eval --run-id … --start … --end …` emits per-refit OOS pooled R², rank-Spearman, sign-agree, top-decile, coverage, disjoint stability + in-sample R²; means reproduce the README (~0.746 / 0.468) on 2025.
* [ ] **S1.3** — after `--persist-eval`, every in-range `sf_window_meta` row for the run has non-NULL `oos_r2` and `coverage`.
* [ ] **S1.4** — `sweep_ibp.py` ranks by an OOS metric; grid covers the extended window/λ/refit ranges; output includes the SF decay curve.
* [ ] **S1.5** — chosen operating point recorded here with the OOS before/after table; R1 marked resolved.
