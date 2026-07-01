# B1 - rename-congestion-metrics

Type: refactor
Branch: refactor/rename-congestion-metrics

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

* [ ] `compute/fragility.py` removed; `compute/congestion.py` exports the four symbols.
* [ ] `_build_result_at` result dict contains `modeled_congestion`, `binding_proximity`; meta contains `modeled_congestion_total`, `modeled_congestion_abs_total`, `modeled_congestion_top10_share`, `binding_proximity_max`, `binding_proximity_p95`; old keys absent from meta.
* [ ] `verify_sign_convention.py` exits 0 on the DFW snapshot; passing convention documented inline in `congestion.py`.
* [ ] `compute/test_snapshot.py` passes without DB writes.
* [ ] No `fragility` symbol referenced outside docs anywhere under `compute/`.
