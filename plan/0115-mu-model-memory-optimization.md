# 0115 - mu-model-memory-optimization

Type: refactor
Branch: refactor/0115-mu-model-memory-optimization

## Goal

* Build full-history μ predictions without requiring one in-memory denormalized panel.
* Attach geography and weather features without daily-frame concatenation or full-panel merge copies.
* Walk historical score weeks in bounded chunks and emit the same combined prediction artifact.

## Context

* A 2025-01-01 full-history run exits 137 during `build_panel`, after weather feature calculation and before the existing panel mmap step.
* `geo_panel` and `wx_panel` duplicate weekly matrices per delivery day, then concatenate and merge them into an already-wide panel.
* `MU_SPILL_PANEL` reduces memory only after `build_panel` returns; it cannot reduce assembly-time peak memory.

## Approach

* Work in: `compute/mu/features.py`, `compute/mu/geo.py`, `compute/mu/weather.py`, `compute/mu/mu_model.py`, and focused μ tests.
* Entry point / primary change: `build_panel()` and `walk_forward()`.
* Replace geo/weather daily-frame accumulation and full-frame merges with week/key lookups that attach feature columns directly, retaining identical causal windows, values, and NaNs.
* Add an explicit chunked historical-walk mode: build each score-week chunk with its required 240-day context, fit/write its predictions, release memory, then combine chunks into the existing `mu_preds.npz` schema in chronological order.
* Log chunk bounds, row counts, and peak-relevant phase transitions for failed-run diagnosis.
* Do NOT touch: feature definitions, score dates, model hyperparameters, causal cutoffs, scoreboard metrics, or output schemas.

## Acceptance

* [ ] Focused tests prove direct geo/weather attachment matches the current assembled panel exactly, including missing values.
* [ ] Chunked and unchunked walks produce equivalent weekly metrics and `mu_preds.npz` contents on a fixture.
* [ ] A full-history run keeps assembly memory bounded per chunk and logs each completed chunk before releasing it.
* [ ] Existing μ tests pass.
