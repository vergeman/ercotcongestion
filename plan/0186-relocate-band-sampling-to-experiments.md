# 0186 - relocate-band-sampling-to-experiments

Type: refactor
Branch: refactor/0186-relocate-band-sampling-to-experiments

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Move `compute/projection/sampling.py` (band Monte-Carlo) into `compute/experiments/mu/`, out of the production projection namespace.
* Keep `experiments/mu/rerank.py` runnable against the relocated module — it is the only remaining consumer.
* Drop the retired band symbols from the production facade and its import-boundary allowlist so `projection/` reads as point-only.

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* Plan 0169 made the nodal forecast deterministic; `propagate_window` is now point-only (`point = −(E_mu · SF)`) and no serving/backfill path imports `sampling.py`.
* The p10/p50/p90 band feature is retired; `sampling.py`'s only live importer is the archived-but-runnable `experiments/mu/rerank.py`, so band code sitting in `compute/projection/` misreads as production capability.
* Pre-existing debris to clean up alongside: `test_forecast_day.py` still calls `propagate_window(..., eps=, n_draws=, rng=)` against the current signature that has none of those params — that reconciliation test is already broken by 0169.

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `compute/projection/`, `compute/experiments/mu/`, `compute/mu_forecast/tests/`
* Entry point / primary change: `git mv compute/projection/sampling.py compute/experiments/mu/sampling.py`
* Repoint `experiments/mu/rerank.py:50` import to `from compute.experiments.mu.sampling import draw_congestion, residual_pool`.
* Remove any `sampling` re-export from `projection/propagate.py` / `projection/__init__.py`, and delete `N_DRAWS`, `band_metrics`, `draw_congestion`, `residual_pool` from the `compute.projection.propagate` set in `test_import_boundaries.py`.
* Split the band/sampling tests out of `test_propagate.py` into a new `compute/mu_forecast/tests/test_sampling.py` importing from `compute.experiments.mu.sampling`; leave the `propagate_window` point-forecast tests in `test_propagate.py`.
* Fix the stale reconciliation test in `test_forecast_day.py` (lines ~695–706): rewrite for the point-only `propagate_window` signature, or remove it — drop its `N_DRAWS`/`residual_pool` import.
* Keep the "retired band metrics" guard tests (`test_grade_day.py::test_rows_do_not_expose_retired_band_metrics`) — they stay as insurance.
* Do NOT touch: `mu_preds.npz` / `mu_nodal.npz` generation, `propagate.py`'s point math, or `experiments/mu/rerank.py` logic beyond the import line.

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [x] `compute/projection/sampling.py` no longer exists; `compute/experiments/mu/sampling.py` does.
* [x] `grep -rn "projection.sampling" compute/` returns nothing.
* [x] `python -m compute.experiments.mu.rerank --help` imports cleanly against the relocated module.
* [x] `test_import_boundaries.py` allowlist no longer lists band symbols; the suite passes.
* [x] Band tests live in `test_sampling.py`; `test_propagate.py` covers only `propagate_window`; `test_forecast_day.py` no longer imports from `sampling`.
* [ ] Full `compute` test suite is green. The refactor's targeted suite passes; two pre-existing hero-text expectation failures remain. The optional slow reconciliation test reaches the corrected point-only call but is fixture-blocked because `/compute/mu/mu_preds.npz` is absent.
