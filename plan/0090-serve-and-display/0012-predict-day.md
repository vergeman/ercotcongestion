# 0012 - predict-day

Type: feat
Branch: feat/0012-predict-day

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Extract the per-week body of `walk_forward()` into a shared fold routine, and add `predict_day(panel, D)` — one iteration of that loop with the prediction block set to D's 24 hours (spec §3.1).
* Emit `wp` for D as `(interval_ts, key, p_bind, mu_gbm)` — exactly the shape `propagate_window` consumes — over the candidate universe = constraint keys present in the trailing window's binding history.
* Emit a novelty count: keys enforced in D−1's data that the trailing window never fit, so a coverage gap is reported, not silently zeroed (spec §3.1, §7).

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* `spec-phase2b-forecast-day.md` §1 (fit-then-predict — the model persists preds, never boosters, so the heads are refit at run time), §3.1 (`predict_day`), §7 (novelty), §10 (extract vs re-fit). This is stage 1 of the two-stage job; **0013** wires it into `forecast_day` and propagation.
* `walk_forward()` (`compute/mu/mu_model.py:352`) already *is* "fit both heads on a trailing window, predict the next block": the fold loop (`:398`) slices `train`/`score`, calls `target_encoding`/`apply_encoding` (`:145`,`:165`), `fit_bind_head`/`fit_mu_head`/`fit_mu_climatology` (`:202`,`:281`,`:251`), over `feature_cols(panel, arms)` (`:108`). `predict_day` is that fold with `score` = D's hours.
* Prefer **extracting** the fold body so the production fit and the validated fit are literally the same code — a re-fit that drifts from `walk_forward` is the failure this branch exists to prevent (spec §10). The bit-identity guards on `walk_forward` (`test`/`compare_base`) pin that the extraction changes nothing.
* Forward inference is legal by construction: `features.build_panel` (`compute/mu/features.py:466`) reads every covariate at the DAM-close vintage (`_dam_close_expr`, `history_cutoff`), so the panel for *tomorrow* is buildable *today*. **This branch does not read live inputs** — it operates on a panel handed to it; the cutoff/leakage story lands in 0013 where `forecast_day` builds that panel.

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `compute/mu/mu_model.py` only.
* **Extract the fold body** (`walk_forward` `:398`–end-of-loop) into a private helper, e.g. `_predict_fold(train, score, arms) -> pd.DataFrame` returning the per-`(hour, key)` rows with `p_bind`, `mu_clim`, `mu_gbm` (the realized `y_bind`/`y_mu` join stays in `walk_forward`, which has the labels; the fold routine itself produces predictions only). Reuse `target_encoding`, `apply_encoding`, `fit_bind_head`, `fit_mu_head`, `fit_mu_climatology`, `feature_cols`, `feature_cols`'s `keep`/`cols` slimming verbatim — no re-derivation.
* **`walk_forward` becomes a thin loop** over `_predict_fold`: same `refit_boundaries`, same skip conditions (`train.empty or score.empty or train["y_bind"].sum() < 10`, `:413`), same log lines, same returned `(predictions, weekly)`. The memory discipline in the loop comment (`:419`–) must survive the extraction — keep the bind matrix filled from the panel view + the single encoded column, not a full-width `apply_encoding` copy.
* **`predict_day(panel, D, *, train_days=DEFAULT_TRAIN_DAYS, arms=("lag","geo","wx")) -> pd.DataFrame`**: `train` = `[D − train_days, D)`, `score` = the 24 hours of D (the fold's prediction block). Candidate universe = keys present in `train`'s binding history — a key with no history has no features and gets no row (spec §3.1). Return `wp` = `(interval_ts, key, p_bind, mu_gbm)`; drop `mu_clim`/labels from the served shape (propagation reads `p_bind`,`mu_gbm`).
* **Arms = the shipped `all`** (`("lag","geo","wx")`), matching the validated config; do not add an arm knob beyond what `walk_forward` already takes.
* **Novelty**: return (or log) the count of keys enforced in D−1's binding history that are absent from the trailing-window fit universe (spec §7). Surface it on the result, not buried — 0013's run log consumes it.
* Do NOT touch: `propagate.py` (stage 2 / `forecast_day` is 0013), `features.py` (the panel builder + DAM-close reads are read as-is; live-input plumbing is 0013), the CLI `main` (`:550`), `mu_bands_weekly.csv`, or the arm/policy definitions. No live DB reads here.

## Commits

<!-- Grouped so the module imports and the walk_forward guards still pass at branch end. -->

* **Commit A — `refactor(mu_model): extract _predict_fold; walk_forward calls it`**
  * `mu_model.py` — fold body → `_predict_fold(train, score, arms)`; `walk_forward` reduced to the boundary loop + label join. Behavior byte-identical; `test`/`compare_base` bit-identity still green.
* **Commit B — `feat(mu_model): predict_day — one fold, prediction block = D`**
  * `mu_model.py` — `predict_day(panel, D, ...)` over the trailing-window candidate universe; returns `wp` `(interval_ts, key, p_bind, mu_gbm)`.
* **Commit C — `feat(mu_model): predict_day novelty count`**
  * `mu_model.py` — count of D−1 keys with no trailing-window fit history, returned/logged for the run summary.
* **Commit D — `test(mu_model): predict_day reconciles with walk_forward (stage 1)`**
  * `compute/mu/tests/` — for a historic D inside a validated span, `predict_day` reproduces `walk_forward`'s `wp` rows for D to bit-identity (same fold, same fit); the fold extraction leaves `walk_forward`'s golden output unchanged; a key absent from the trailing window yields no row and increments novelty.

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [ ] `_predict_fold` extraction leaves `walk_forward`'s `(predictions, weekly)` byte-identical — existing `test`/`compare_base` bit-identity guards pass unchanged.
* [ ] `predict_day(panel, D)` returns `(interval_ts, key, p_bind, mu_gbm)` for D's 24 h over exactly the keys present in `[D−train_days, D)` binding history; no row for a historyless key.
* [ ] **Stage-1 reconciliation:** for a historic D inside a validated backtest span, `predict_day`'s `wp` for D equals the `wp` `walk_forward` produces for D (same trailing window) to tolerance — if they disagree, one fit path has drifted (spec §9).
* [ ] Novelty count = number of keys enforced in D−1 data absent from the fit universe; returned/logged, non-fatal (spec §7).
* [ ] `pytest` green; `propagate.py`, `features.py`, and the CLI untouched.
