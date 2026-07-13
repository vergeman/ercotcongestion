# 0082 oos-eval-and-resweep — DONE

Type: feat · Branch: feat/0082-oos-eval-and-resweep

## Goal

Make the honest out-of-window fit (`window_end = refit_start`) production
infrastructure — one reusable per-refit metric pass the sweep and
`sf_window_meta` both use — then re-select the operating point on it.
Retires **R1** (does the point move under honest selection?) and **R2** (is the
19% coverage gap seasonal?). Prior in-sample `fit_r2 ≈ 0.986` masks the honest
OOS ~0.746 / disjoint stability ~0.468.

## Changes

* **`sf/coverage_probe.py`** (new) — the R2 probe. Splits novel μ-mass into seasonal vs genuinely-new over extended history.
* **`sf/eval.py`** (new) — `evaluate()` (per-refit honest OOS metrics + in-sample R², 3 fits/week), `sf_decay()` (drift curve), `--persist-eval`, `--emit-decay`. Self-contained: metric fns lifted from the frozen `experiments/` harness, not imported, to keep the kept→frozen edge cut.
* **`sf/sweep_ibp.py`** (rewritten) — loads panels ONCE, scores combos in-process via `evaluate`, ranks on OOS (`--rank-by`, default `oos_pooled_r2`); emits winner's decay curve.
* **`sf/persist.py`** — `update_eval_metrics` (UPDATE by `score_start`, datetime param), `count_null_eval`.
* Deferred: `fit.py` / `runner.py` carry a comment pointing at the chosen defaults; values changed at S5, not here.

Untouched: `fit.py`/`rolling.py` fit math, served `bp_ercot`/`implied_binding_proximity`, the frozen `experiments/` scripts.

## Acceptance — all verified

* [x] **S1.1 — R2 = qualified NO.** 81 weeks. Coverage 0.814 (reproduces the ~19% gap). Seasonal share of novel mass 0.507 (bound at all) / 0.303 (bound ≥25h). ⇒ Warm-start recovers only ~30–50%; the rest (shoulder-season novel constraints) needs shorter refit, not a free lunch.
* [x] **S1.2** — `evaluate()` emits all listed metrics. On the README's 43-week window, reproduces within noise (OOS 0.750/0.746, Spearman 0.833/0.835, sign 0.906/0.907, top-dec 0.785/0.780). Full 52-week is more conservative (OOS 0.704) — backfill adds 8 harder early-winter weeks.
* [x] **S1.3** — persist a run (4 windows, NULL `oos_r2`) → `--persist-eval` → all 4 non-NULL (`oos_r2` 0.793–0.914 vs `fit_r2` 0.983–0.987), 0 remaining. Straddling week matched via untrimmed `df_full`.
* [x] **S1.4** — sweep ranks on OOS; one-time panel load, in-process combos, winner decay curve. Sanity check: ranking flips vs the in-sample objective (λ=10 > λ=0.1 on OOS while lower in-sample) — the ridge was decorative.
* [x] **S1.5 — R1 RESOLVED, the point moves.** Two-pass sweep, 18mo. **Chosen: `window=240, refit=7, λ=1.0, std_floor=100, min_hours=25`.**

  | config | OOS R² | Spearman | sign | top-dec | coverage | drift@60d |
  |---|---|---|---|---|---|---|
  | current (60, 0.1) | 0.708 | 0.799 | 0.897 | 0.751 | 0.810 | 0.459 |
  | **chosen (240, 1)** | **0.734** | 0.803 | 0.895 | **0.756** | **0.861** | **0.832** |

  Ties/beats every screening metric, lifts coverage +0.051, drifts far less over the refit horizon. Confirms old λ=0.1 was decorative (XᵀX diag ≈1440), 60d too short. Not swept: `std_floor`, `min_hours`. Sweep CSVs: `sf/ibp_sweep_{coarse,refine}.csv`.

## S5 follow-up

Adopt as code defaults — `fit.py RIDGE_LAMBDA 1e-1→1.0`, `runner.py
DEFAULT_WINDOW_DAYS 60→240` — when promoting a real `(240,1)` run.
`sf_stability` is within-window only (separation = window length); the decay
curve is the fair cross-window drift metric.
