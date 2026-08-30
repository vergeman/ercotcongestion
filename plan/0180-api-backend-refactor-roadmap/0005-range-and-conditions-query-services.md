# 0005 - Range and Conditions query services

Type: refactor
Branch: refactor/0184-range-and-conditions-query-services

## Goal

* Extract the remaining substantial range and Conditions query assembly from route modules.
* Establish a consistent thin-route/service boundary outside Analysis and Map.

## Context

* Forecast, ERCOT range, and Conditions each currently combine FastAPI inputs, connection management, SQL, and response assembly.
* They already share time and system-lambda helpers, so their service seams are lower risk than a generic repository layer.
* Scoreboard and Topology demonstrate the intended route-to-service pattern.

## Approach

* Work in: `api/forecast.py`, `api/ercot_range.py`, `api/conditions.py`, `api/services/`, and their focused tests.
* Entry point / primary change: add `forecast_range`, `ercot_range`, and `conditions` services whose public functions accept normalized request values and return response schemas.
* Keep FastAPI query validation, dependency injection, and HTTP-specific parameter descriptions in route modules; services own SQL and response construction.
* Preserve each route's current 503 behavior, inclusive interval boundaries, UTC normalization, forecast-horizon coalescing, lambda fallback, and Conditions vintage/no-lookahead policy.
* Do NOT extract trivial scalar helpers into separate modules unless they are shared by more than one domain.
* Do NOT touch: endpoint paths, query contracts, ingestion tables, or client payload compression formats.

## Acceptance

* [x] Forecast, ERCOT range, and Conditions routes contain no SQL or response assembly loops.
* [x] Services are unit-testable against the existing fake-pool/cursor seams.
* [x] Focused Forecast, ERCOT range, Conditions, and OpenAPI tests pass without contract changes.
