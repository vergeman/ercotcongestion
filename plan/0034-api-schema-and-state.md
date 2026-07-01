# B1 - api-schema-and-state

Type: refactor
Branch: refactor/0034-api-schema-and-state

## Goal

* Rename `fragility` → `modeled_congestion` in `BusState`, `SnapshotMeta`, and `ScatterPoint`; add `binding_proximity` to `BusState` and the five new meta keys to `SnapshotMeta`.
* Swap column lists in `api/state.py` for both `/api/state` and `/api/state_range` so single-frame and range responses read the new columns.
* Update `api/tests/test_state.py` fixtures + add a schema regression guard, and fix the comment in `api/services/ptdf_service.py:42`.

## Context

* Depends on Sprint 2A Migration A landed - new columns exist and are populated on new writes.
* Small, mechanical change; unblocks 2C from starting to compile against the new Pydantic types.
* Does NOT touch `api/validation.py` - that's B2 (its endpoint semantics change requires its own commit).
* No public API contract - only known consumer is `web/src/` (2C). Break freely.

## Approach

* Work in: `api/models.py`, `api/state.py`, `api/services/ptdf_service.py`, `api/tests/test_state.py`
* `api/models.py`:
  * `BusState`: `fragility: float | None` → `modeled_congestion: float | None`; add `binding_proximity: float | None`.
  * `SnapshotMeta`: `fragility_total`/`fragility_top10_share` → `modeled_congestion_total`, `modeled_congestion_abs_total`, `modeled_congestion_top10_share`, `binding_proximity_max`, `binding_proximity_p95`.
  * `ScatterPoint`: `fragility: float` → `modeled_congestion: float`; keep `abs_basis`. `abs_modeled_congestion` / signed `basis` deferred to B2 (they only matter to the validation endpoint).
* `api/state.py`:
  * Line 65 (single-timestamp): `SELECT bus_id, fragility, lmp, basis` → `SELECT bus_id, modeled_congestion, binding_proximity, lmp, basis`.
  * Line 120 (range): same swap.
  * `META_COLS` at line 33: leave as `*` for now - accepts both old and new meta columns during the dual-write window. Tightening is out of scope for this branch.
* `api/services/ptdf_service.py` line 42: `compute/fragility.py` → `compute/congestion.py`.
* `api/tests/test_state.py`:
  * Lines 26-27: swap meta fixture keys to the new five.
  * Lines 41-42, 66-69: bus fixture dicts - swap `fragility` → `modeled_congestion`; add `binding_proximity`.
  * Add a schema regression assertion: response bodies carry `modeled_congestion` + `binding_proximity` on every bus and contain no `fragility` key.
* Do NOT touch: `api/validation.py`, `api/models.py::ValidationResponse`/`CorrelationResult`, frontend, DB, `compute/`.

## Acceptance

* [x] `grep -rn "fragility" api/` returns hits only inside `api/validation.py` (deferred to B2) and the `'fragility' not in bus` regression assertions in `test_state.py`.
* [x] `GET /api/state?t=<ok-ts>` returns each bus with `{bus_id, modeled_congestion, binding_proximity, lmp, basis}` and no `fragility` key.
* [x] `GET /api/state_range?start=&end=` returns entries of the same shape.
* [x] `api/tests/test_state.py` fixtures updated; regression guard added to both state and state_range tests.
* [x] `api/services/ptdf_service.py` comment points at `compute/congestion.py`.

Note: `api/validation.py` will not import cleanly until B2 lands (references renamed `ScatterPoint.fragility`).
