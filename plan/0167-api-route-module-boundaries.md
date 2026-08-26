# 0167 - API route module boundaries

Type: refactor
Branch: refactor/0167-api-route-module-boundaries

## Goal

* Split oversized API route and schema modules into domain-owned, importable modules without changing public routes or response payloads.
* Centralize duplicated request, time, constraint-key, settlement-point metadata, and bootstrap helpers.
* Preserve artifact selection, CT delivery-date behavior, caching, SQL semantics, and OpenAPI contracts while making route handlers thin orchestration layers.

## Context

* `api/analysis.py` (1,953 lines), `api/models.py` (1,241 lines), and `api/map.py` (921 lines) combine unrelated domains, data access, transformations, and route registration.
* `map.py` and `matrix.py` independently load/cache the same settlement-point CSV metadata; several modules duplicate UTC/CT, constraint-key, run-selection, and bootstrap helpers.
* Brief and Map/Scoreboard bootstrap endpoints currently call decorated route handlers directly, coupling service composition to FastAPI dependency defaults.
* The API has route-level unit coverage, including explicit contracts for artifact availability, fallback behavior, CT boundaries, response models, and cache behavior; those contracts must remain unchanged.

## Approach

* Work in: `api/`, `api/services/`, and `api/tests/`.
* Entry point / primary change: replace the flat `analysis.py`, `map.py`, and `models.py` ownership boundaries with domain packages while retaining stable routers and import compatibility during migration.
* Add neutral shared modules for server-selected run dependencies, UTC/Chicago time handling, canonical constraint-key parsing/normalization, settlement-point coordinates/metadata caching, and reusable bootstrap soft-fail/availability construction; migrate exact duplicates to them.
* Make `services.sf_artifacts.resolve_daily_horizon` the one horizon resolver and retain artifact lookup/cache behavior in `services.sf_artifacts`; do not introduce a generic repository abstraction for domain-specific map fallback or analysis history behavior.
* Split schemas into `api/schemas/analysis.py`, `map.py`, `matrix.py`, `scoreboard.py`, `conditions.py`, and `common.py`; leave `api/models.py` as a temporary re-export façade until all in-repository imports use the owning modules.
* Extract analysis dataframe/query work into services for artifact profiles/projections, trailing histories, and attribution/standout selection; move node/vocabulary, grade, insight, and Brief endpoints into separate subrouters under `api/analysis/routes/`.
* Move Brief hero and section composition to service functions. Route wrappers may call those functions, but composed Brief responses must no longer invoke decorated FastAPI handlers or depend on raw `Query(...)` defaults.
* Split map interaction (`exposures`, `reach`), overview, ranked-constraint, and summary endpoints into `api/map/routes/`; use the shared settlement-point service and move scoreboard headline construction behind a non-route service callable by both Scoreboard and Map summary.
* Extract Matrix selection/ranking policy into a focused module and keep `matrix/frame` as validation, artifact resolution, and response assembly; similarly separate Scoreboard aggregation and bootstrap composition, and extract Forecast query/result assembly from its long route handler where it does not alter route semantics.
* Retain root-mounted paths and router tags in `api/main.py`; use narrow compatibility façades/re-exports only while tests and remaining consumers migrate, then remove dead façades in a follow-up once external compatibility needs are known.
* Split tests by route/service domain and provide explicit cache-reset fixtures rather than monkeypatching newly private module cache globals; retain existing availability, fallback, CT-boundary, OpenAPI, and response-equivalence assertions.
* Do NOT touch: public URL paths and query parameters, response JSON/schema names, database schema and SQL results, artifact formats, run/horizon selection policy, CT delivery-date rules, map fallback semantics, or unrelated compute/documentation changes.

## Acceptance

* [ ] `analysis`, `map`, and schema modules are split by domain, with root-mounted routes, tags, request parameters, response models, and JSON payloads unchanged.
* [x] One shared implementation owns each duplicated UTC/CT rule, constraint-key parser, server-selected-run dependency, settlement-point metadata cache, bootstrap soft-fail, and bootstrap availability status.
* [x] Production route modules import schemas through domain-specific `api/schemas/` modules while `api/models.py` remains the temporary compatibility source.
* [ ] Brief and Map/Scoreboard composition call non-route service functions; no composition path passes FastAPI `Query(...)` sentinel defaults to another handler.
* [ ] Matrix, Map, and Analysis retain their current artifact availability, horizon, CT delivery-date, interval-gate, and nearest-past fallback behavior.
* [ ] Schema definitions resolve from their owning modules, with `api/models.py` reduced to compatibility exports only where migration requires them.
* [ ] Existing API unit tests and OpenAPI tests pass; new focused service/cache tests cover the extracted shared helpers and route-equivalence tests protect refactored endpoints.
