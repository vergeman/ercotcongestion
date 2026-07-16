# 0008 - propagate-window-refactor

Type: refactor
Branch: refactor/0008-propagate-window-refactor

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Extract the per-week body of `walk()` into a shared `propagate_window(...)` that both the backtest and (later) `forecast_day` call.
* Tee the per-SP P10/P50/P90 panel and the deterministic point forecast `E[μ]·SF` out of the arrays already computed, returned as a `NodalPanel` — in memory only, nothing persisted.
* Keep `mu_bands_weekly.csv` byte-identical to a pre-change baseline: `walk()`, `band_metrics`, `r5()`, and the CLI default are unchanged.

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* `spec-phase2a-nodal-panel.md` §3 (the refactor), §4 (deterministic point), §7 (golden guard), §10 (consistency/alignment/determinism). This is the one structural change on the critical path — every other branch in the sprint rides on it.
* Today `walk()` (`compute/mu/propagate.py:129`) computes `draws`, calls `band_metrics` (`:109`) which does `np.percentile(draws, QUANTILES, axis=0)` and collapses to scalars, then frees the percentiles. The panel we want is that exact array, discarded.
* The point forecast is **not** the sampling median — it is `E[μ]=P(bind)·E[μ|bind]` pushed through SF, reusing the `P`, `MU`, `SFm` arrays already built inside `draw_congestion` (`:84`). Store it alongside p50; they differ.
* No modeling change, no new output file, no schema. Additive dataclass + function seam only.

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `compute/mu/propagate.py` only.
* **`NodalPanel` dataclass** (spec §3): `ts (H,)`, `settlement_points (N,)=SF.columns`, `p10/p50/p90 (H,N) f32`, `point (H,N) f32`, `sf_r2 (N,)|None`. Node axis is ragged week-to-week — preserve `SF.columns` as-is, never union/fill.
* **Factor the percentile call.** `band_metrics` and the panel must read **one** `np.percentile(draws, QUANTILES, axis=0)` so the scored p50 and served p50 can never diverge. Either have `propagate_window` compute the percentiles once and pass them into `band_metrics`, or have `band_metrics` return them for reuse — pick the smaller diff, but there must be a single call.
* **Deterministic point** (spec §4): inside/next to `draw_congestion`, add a no-sampling branch `E_mu = P * MU` (H,K), `point = -(E_mu @ SFm)` (H,N). Reuse the existing `P`, `MU`, `SFm`; no second SF multiply. Mirror the `C = −μ·SFᵀ` sign convention already used for `Y`.
* **`propagate_window(s, end, M, C, wp, eps, n_draws, rng, *, want_panel=False) -> tuple[dict|None, NodalPanel|None]`** (spec §3 signature): fit SF on `[s−WINDOW_DAYS, s)`, score/draw over `[s, end)`, build the metrics row exactly as today; when `want_panel`, also build the `NodalPanel`. Returns `(row, None)` when `want_panel=False`.
* **`walk()` becomes a thin loop**: build `eps`/`SF`/`hours`/`wp` as today, call `propagate_window(..., want_panel=False)`, append the returned row unchanged. Same skip conditions (empty pool, empty `M_fit`/`SF`, empty `hours`) and same log lines.
* `sf_r2`: populate from the SF fit if `implied_shift_factors` already exposes per-SP R²; otherwise leave `None` (spec §10/§11 — fit confidence otherwise defers to IBP diagnostics).
* Do NOT touch: `band_metrics`' returned dict keys/values, `r5()`/`gate()`/`existence_test()`, the CLI (`main`, args), `mu_bands_weekly.csv` shape, or any other module. No `--nodal-out`, no npz, no DB — those are 0009+.

## Commits

<!-- Grouped so the module imports and the golden file matches at branch end. -->

* **Commit A — `refactor(propagate): single percentile call shared by metrics + panel`**
  * `propagate.py` — factor `np.percentile(draws, QUANTILES, axis=0)` to one site; `band_metrics` reads it. No behavior change; `mu_bands_weekly.csv` still byte-identical.
* **Commit B — `feat(propagate): NodalPanel + deterministic point in draw_congestion`**
  * `propagate.py` — `NodalPanel` dataclass; `E_mu`/`point` branch reusing `P`/`MU`/`SFm`. Not yet wired into a returned panel.
* **Commit C — `refactor(propagate): extract propagate_window; walk() calls it`**
  * `propagate.py` — new `propagate_window(..., want_panel=False)`; `walk()` reduced to the loop + row append. Metrics row byte-identical when `want_panel=False`; panel built when `want_panel=True`.

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [x] **Golden file:** re-running the backtest CLI (no new flags) produces `mu_bands_weekly.csv` byte-identical to a pre-change baseline (spec §7, §10). — verified: full backtest regen matches committed baseline, sha256 `01abe45a…`.
* [x] **Consistency:** for a week, `nanmean` over the panel's `p90−p10` and the `Y∈[p10,p90]` mask reproduce that week's `band_width` / `coverage80` from `band_metrics` — same percentile call (spec §10). — `test_panel_reduces_to_the_same_metrics_as_the_row`.
* [x] **Alignment:** panel node axis `== SF.columns`, hour axis `== hours`; a spot node's `point` equals `-(E_mu @ SF)[:, n]` recomputed independently (spec §10). — `test_panel_reduces_to_the_same_metrics_as_the_row` (axes) + `test_want_point_is_the_expectation_not_the_median` (independent point recompute).
* [x] **Determinism:** fixed `--seed` reproduces `p10/p50/p90` bit-for-bit across two runs (spec §10). — `test_panel_is_bit_for_bit_deterministic_under_fixed_seed` (also `point`).
* [x] `walk()` returns the identical weekly-metrics DataFrame; `r5()` verdict unchanged; no new files or DB writes. — golden-file byte-identity + `test_want_panel_does_not_perturb_the_metrics_row`; r5 verdict still `NOT THE PRODUCT`, coverage 0.673.
