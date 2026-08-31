# 0004 - Map domain services

Type: refactor
Branch: refactor/0183-map-domain-services

## Goal

* Extract Map detail and aggregate query policy into callable domain services.
* Make Map summary composition independent of route handlers.

## Context

* `api/map.py` is 861 lines across metadata, click/detail, aggregate, ranked, and bootstrap-summary concerns.
* Its summary currently calls the decorated `get_map_overview` handler directly.
* Existing shared artifact, settlement-point, headline, topology, and bootstrap services provide stable collaborators for an extraction.

## Approach

* Work in: `api/map.py`, `api/services/map/`, `api/schemas/map.py`, and `api/tests/test_map.py`.
* Entry point / primary change: introduce a detail service for exposures/reach and an aggregate service for meta, overview, and ranked constraints.
* Keep Map-specific run/window resolution, artifact-day fallback, geographic enrichment, ranking bases, and response assembly inside the matching service; reuse existing shared services rather than copying helpers.
* Add a summary service that concurrently composes aggregate overview/meta, Scoreboard headline, and topology through undecorated callables.
* Leave HTTP validation and `APIRouter` registration in a thin Map route module; preserve test-only metadata overrides through an explicit injected collaborator or fixture seam.
* Do NOT touch: SF artifact format, SF clipping/ranking semantics, Map response shape, 503 fallback policy, or topology cache behavior.

## Acceptance

* [x] No Map route handler calls another decorated Map route handler.
* [x] Detail, aggregate, and summary services do not import `api.map`.
* [x] Existing Map tests cover the same day-aware artifact, ranking, metadata, and summary soft-fail behavior.
* [x] OpenAPI and all `/map/*` paths remain unchanged.
