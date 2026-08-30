# 0180 - API backend refactor roadmap

Type: refactor

## Goal

* Complete the API boundary work begun in plan 0167 without changing public contracts.
* Reduce route modules to HTTP validation, delegation, and response handling.

## Sequence

1. [0001 - Authoritative domain schemas](0001-authoritative-domain-schemas.md)
2. [0168 - Matrix selection service](../0168-matrix-selection-service.md) — existing, uncompleted plan
3. [0002 - Analysis query services](0002-analysis-query-services.md)
4. [0003 - Analysis routes and Brief composition](0003-analysis-routes-and-brief-composition.md) — completed
5. [0004 - Map domain services](0004-map-domain-services.md)
6. [0005 - Range and Conditions query services](0005-range-and-conditions-query-services.md)
7. [0006 - Route package and import migration](0006-route-package-and-import-migration.md)

## Guardrails

* Keep root-mounted URLs, query parameters, response model names, payloads, OpenAPI, run/horizon policy, CT delivery-day rules, cache behavior, and SQL semantics unchanged.
* Retain the current top-level import convention until the final package-import migration.
* Each numbered implementation plan is an independently releasable branch; do not combine steps merely because they touch a common route.
