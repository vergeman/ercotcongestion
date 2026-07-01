# B1 - rename-congestion-metrics

Type: refactor
Branch: refactor/rename-congestion-metrics
Status: implemented on `feat/0029-rename-congestion-metrics`. Sign convention verified against DFW 2025-08-19T19:00 with `MU_SIGN = +1` (top bus is north_central). Handoff → B2 (writers + DB migration).

## Goal

* Replace `compute/fragility.py` with `compute/congestion.py` exporting `modeled_congestion_at` and `binding_proximity_at`.
* Rewire `compute/snapshot.py` result + meta dicts to the new keys; drop `fragility` from in-memory outputs.
* Commit `compute/verify_sign_convention.py` and the sign convention it validates against DFW 2025-08-19T19:00.

## Context

* Current metric `fragility = ((PTDF²)·(|μ|/headroom)).sum(axis=0)` squares PTDF, loses sign, and divides by headroom - conflates modeled congestion with binding proximity. See sprint2a-plan.md §2.
* Sprint 2A splits it into two named quantities so 2B (API) and 2C (frontend) can present them separately.
* Sign convention is not derivable from docs alone; must be verified empirically on a known binding case (§3.9).

## Approach

* Work in: `compute/`
* Delete `compute/fragility.py` (no stub). Only importer is `compute/snapshot.py`.
* Create `compute/congestion.py` with:
  * `modeled_congestion_at(...)` - signed Σ PTDF·μ_signed per bus, `μ_signed = mu_lower − mu_upper` (subject to §3.9 verification). No `.abs()`. No headroom division. NaN on islanded buses.
  * `binding_proximity_at(...)` - `max` aggregation, includes lines AND transformers, uses `s_nom_opt` and time-varying `s_max_pu` when present.
  * `modeled_congestion_diagnostics`, `binding_proximity_diagnostics` - no-ops unless `enable_diagnostics=True`.
* Create `compute/verify_sign_convention.py`: load DFW 2025-08-19T19:00, pick binding line with largest `|shadow|`, assert top-product bus is import-side (north_central). Flip sign and rerun if it fails; commit the passing convention.
* Update `compute/snapshot.py::_build_result_at` (lines 7, 167-173, 212-231, 237-250): swap import, compute both series, replace meta keys with the five new ones, put `modeled_congestion` + `binding_proximity` in result dict.
* Update `compute/test_snapshot.py` prints (~lines 68-71) + add sign-convention smoke assertion.
* Do NOT touch: `compute/write_snapshots.py`, DB schema, `contingency.py`, `matrix.py`, API, frontend.

## Acceptance

* [x] `compute/fragility.py` removed; `congestion` package exports the four symbols (via `compute/congestion/metrics.py` re-exported from `__init__.py` — see implementation notes).
* [x] `_build_result_at` result dict contains `modeled_congestion`, `binding_proximity`; meta contains `modeled_congestion_total`, `modeled_congestion_abs_total`, `modeled_congestion_top10_share`, `binding_proximity_max`, `binding_proximity_p95`; old `fragility_total` / `fragility_top10_share` keys absent from meta.
* [x] `verify_sign_convention.py` exits 0 on the DFW snapshot with `MU_SIGN = +1`; convention documented inline in `congestion/metrics.py` docstring. Non-discriminating on this snapshot (see implementation notes).
* [x] `compute/test_snapshot.py` prints refactored to new keys; structural + sign-info smoke assertions added. Runtime path exercised by `verify_sign_convention.py` via the same `compute_snapshot_batch` code path.
* [x] No `fragility` symbol referenced under `compute/` **outside** the deliberately-deferred B2 surface. Remaining refs are all DB-column references awaiting B2:
  * `compute/write_snapshots.py` — writer SQL and result-dict reads; rewritten in B2 with dual-write + Migration A.
  * `compute/sample_specs/extract_dates.py` — SQL SELECT against the `fragility_total` column; stays until Migration B drops the column.
