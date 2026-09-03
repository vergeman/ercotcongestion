# 0193 - Matrix frame service

Type: refactor
Branch: refactor/0193-matrix-frame-service

## Goal

* Move `/matrix/frame` orchestration, selection, and frame assembly into a focused Matrix service.
* Keep the route, query parameters, response schema, and matrix-selection behavior unchanged.
* Replace route-global and cursor-order-coupled test seams with explicit collaborators.

## Context

* `api/routes/matrix.py` currently combines HTTP normalization, database access, artifact/DAM loading, selection policy, and `MatrixFrame` rendering in one 600-line route module.
* Plan 0168 proposed extracting selection only; this plan completes the boundary by making the route a thin HTTP adapter while retaining the existing artifact and CT delivery-date services.
* Existing tests queue SQL results and patch route-global settlement-point metadata; this couples policy tests to implementation query order.

## Approach

* Work in: `api/routes/matrix.py`, `api/services/matrix/`, `api/services/sf_artifacts.py`, `api/schemas/matrix.py`, and `api/tests/test_matrix.py`.
* Entry point / primary change: add `api.services.matrix.frame.build_frame()` that accepts a normalized request plus explicit repository and settlement-point metadata collaborators, and returns `MatrixFrame`.
* Introduce a small request/value model for normalized limits, pins, searches, previews, column set, orientation, and row order. Keep FastAPI `Query` declarations and HTTP 422 behavior in the route boundary.
* Move Matrix-specific ranking and bounded-axis policy into `api.services.matrix.selection`; preserve stable ties, pin/search force-inclusion, anchors, hub/default seeds, type filtering, cursor-DAM fallback, and constraint-major wire layout.
* Introduce a narrow Matrix repository interface/implementation for current-run lookup, daily-artifact retrieval, realized DAM `mu`, and constraint-type metadata. Keep `sf_artifacts` as the shared owner of artifact decoding/cache and CT delivery-date calculation; do not duplicate its logic.
* Move unavailable-frame handling, frame extrema, DAM-status calculation, decimal display rounding, and row/column/cell response assembly into the frame service.
* Make settlement-point metadata an injected collaborator at the route/service boundary. Remove `_SP_METADATA` as a production route-global seam and update fixtures/fakes to supply metadata explicitly.
* Remove the duplicate `core_columns` assignment while moving selection code.
* Organize tests around pure selection/frame-service behavior with small DataFrame artifacts, plus a thin route contract suite. Avoid assertions that require a particular sequence of repository SQL calls.
* Do NOT touch: `/matrix/frame` path or query names, `MatrixFrame` wire format, artifact formats/cache policy, `SF_ABS_CAP` semantics, CT boundary semantics, or Map/Analysis endpoint behavior.

## Acceptance

* [x] `api/routes/matrix.py` contains router registration, FastAPI query definitions, HTTP input normalization, and one service invocation; it does not execute Matrix SQL or assemble `MatrixFrame` rows/cells. (686e5d09 — route ends at `build_frame(request, MatrixRepository(get_pool()), metadata)`; no `cur.execute`/`MatrixFrame(...)` in the route.)
* [x] Matrix frame selection, availability handling, and response assembly live under `api/services/matrix/` and do not import the route module. (`frame.py`/`selection.py`/`repository.py`/`models.py`; grep confirms no `api.routes` import under `api/services/matrix/`.)
* [x] Artifact loading and CT delivery-date resolution continue to use `api.services.sf_artifacts` as their sole shared implementation. (`frame.py` imports `delivery_date_for`; `repository.py` imports `load_daily_artifact`/`load_realized_mu` from `sf_artifacts`.)
* [x] Metadata and database access are explicit service collaborators; Matrix tests no longer rely on `_SP_METADATA` or raw cursor-query ordering for selection-policy coverage. (Route metadata via `Depends(get_settlement_point_metadata)`; `_SP_METADATA` removed from matrix; selection/frame coverage in `test_matrix_frame_service.py` uses `FakeMatrixData` with no cursor queue.)
* [x] Existing Matrix behavior is unchanged for availability, CT day boundaries, rounding, row orders, pins, peeks, searches, type filtering, column sets, anchors, hub/default seeds, orientations, caps, truncation fields, and DAM status. (Verified via the passing route-contract suite in `test_matrix.py`, which exercises these behaviors against the wire format.)
* [x] `api/tests/test_matrix.py` passes, with focused service tests covering selection and frame assembly and route tests covering the public HTTP contract. (`docker compose run --rm --no-deps api python -m pytest api/tests/test_matrix.py api/tests/test_matrix_frame_service.py` → 22 passed.)
