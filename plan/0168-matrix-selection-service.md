# 0168 - Matrix selection service

Type: refactor
Branch: refactor/0168-matrix-selection-service

## Goal

* Move Matrix row and column selection policy into a focused service module.
* Keep `/matrix/frame` behavior, bounded inputs, and response payloads unchanged.

## Context

* `api/matrix.py` combines request validation, artifact access, metadata lookup, and two large axis-selection functions.
* Matrix selection depends on bounded pins, searches, anchors, type filtering, cursor μ, and stable ordering rules.

## Approach

* Work in: `api/matrix.py`, `api/services/`, and `api/tests/test_matrix.py`.
* Entry point / primary change: extract `_select_constraints_major` and `_select_nodes_major` with their pure ranking helpers into `services/matrix_selection.py`.
* Pass selection limits and narrow collaborator functions explicitly so the service does not import the Matrix router or create a circular dependency.
* Leave `/matrix/frame` responsible for FastAPI query validation, CT delivery-date/artifact resolution, DAM lookup, and `MatrixFrame` construction.
* Preserve test-visible ordering for pins, searches, anchors, hub seeds, type filters, cursor μ, and bounded caps.
* Do NOT touch: Matrix route path/query names, response models, artifact formats, CT boundary behavior, or Map/Analysis code.

## Acceptance

* [ ] Matrix selection policy is owned by `services/matrix_selection.py`; the route module contains only validation, loading, and response assembly.
* [ ] Existing Matrix tests pass unchanged, including CT-boundary, causal availability, pins, searches, orientations, anchors, and bounded-selection cases.
