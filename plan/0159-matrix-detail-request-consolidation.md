# 0159 - matrix-detail-request-consolidation

Type: refactor
Branch: refactor/0159-matrix-detail-request-consolidation

## Goal

* Serve Matrix node and constraint Detail evidence through consolidated request flows.
* Remove node-selection topology and Detail request fan-out while preserving the rendered facts and footprint filtering.
* Retain lean node analysis for the Basis lens and compatibility APIs for external consumers.

## Context

* `/matrix` fetched `/topology` for node metadata and the embedded node footprint.
* `/analysis/settlement-points` already supplies the same artifact-scoped Nodes index.
* Detail previously fetched driver terms, structural terms, and ESSP membership separately.
* Constraint Detail separately fetched a full evidence reach and a bounded footprint reach.

## Approach

* Work in: `api/analysis.py`, `api/models.py`, `web/src/api/*`, and Matrix Detail/workspace components.
* Add Type, Zone, and nullable coordinates to settlement-point metadata; use it for the Nodes index and footprint.
* Add an opt-in full-detail `/analysis/node` response with driver terms, structural terms, and ESSP count; use it only in Matrix Detail.
* Derive the footprint's existing thresholded, 20-point subset from Matrix Constraint Detail's full reach, avoiding a second bounded reach request.
* Do NOT touch: Map/Brief topology loading, Basis-lens lean requests, or legacy `/analysis/essp` and structural-mode APIs pending an external-consumer audit.

## Acceptance

* [x] A Matrix Nodes response includes Type, Zone, and coordinates for its artifact points.
* [x] Matrix node selection makes one bundled Detail request and no footprint topology request.
* [x] Nodes filters, Detail facts, structural exposure, ESSP count, and the footprint remain populated.
* [x] Constraint evidence and footprint share one full reach response while retaining its thresholded 20-point display subset.
* [x] Focused API tests and web builds pass.
