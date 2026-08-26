# 0167 - API route module boundaries

Type: refactor
Branch: refactor/0167-api-route-module-boundaries

## Goal

* Establish shared API boundaries and domain schema imports without changing public routes or response payloads.
* Centralize duplicated request, time, constraint-key, settlement-point metadata, and bootstrap helpers.
* Preserve artifact selection, CT delivery-date behavior, caching, SQL semantics, and OpenAPI contracts while making route handlers thin orchestration layers.

## Context

* `api/analysis.py` (1,953 lines), `api/models.py` (1,241 lines), and `api/map.py` (921 lines) remain candidates for follow-up physical module splits.
* `map.py` and `matrix.py` independently load/cache the same settlement-point CSV metadata; several modules duplicate UTC/CT, constraint-key, run-selection, and bootstrap helpers.
* Brief and Map/Scoreboard bootstrap endpoints currently call decorated route handlers directly, coupling service composition to FastAPI dependency defaults.
* The API has route-level unit coverage, including explicit contracts for artifact availability, fallback behavior, CT boundaries, response models, and cache behavior; those contracts must remain unchanged.

## Approach

* Work in: `api/`, `api/services/`, and `api/tests/`.
* Entry point / primary change: establish shared helper and schema-import boundaries while retaining stable routers and import compatibility.
* Add neutral shared modules for server-selected run dependencies, UTC/Chicago time handling, canonical constraint-key parsing/normalization, settlement-point coordinates/metadata caching, and reusable bootstrap soft-fail/availability construction; migrate exact duplicates to them.
* Make `services.sf_artifacts.resolve_daily_horizon` the one horizon resolver and retain artifact lookup/cache behavior in `services.sf_artifacts`; do not introduce a generic repository abstraction for domain-specific map fallback or analysis history behavior.
* Split schemas into `api/schemas/analysis.py`, `map.py`, `matrix.py`, `scoreboard.py`, `conditions.py`, and `common.py`; leave `api/models.py` as a temporary re-export façade until all in-repository imports use the owning modules.
* Move Scoreboard headline construction behind a non-route service callable by both Scoreboard and Map summary.
* Retain root-mounted paths and router tags in `api/main.py`, and preserve `api/models.py` as the schema compatibility source during follow-up migrations.
* Do NOT touch: public URL paths and query parameters, response JSON/schema names, database schema and SQL results, artifact formats, run/horizon selection policy, CT delivery-date rules, map fallback semantics, or unrelated compute/documentation changes.

## Acceptance

* [x] Shared-boundary changes retain root-mounted routes, tags, request parameters, response models, and JSON payloads.
* [x] One shared implementation owns each duplicated UTC/CT rule, constraint-key parser, server-selected-run dependency, settlement-point metadata cache, bootstrap soft-fail, and bootstrap availability status.
* [x] Production route modules import schemas through domain-specific `api/schemas/` modules while `api/models.py` remains the temporary compatibility source.
* [x] Map bootstrap calls the Scoreboard headline service directly rather than invoking its decorated route handler.
* [x] Map bootstrap calls a non-route Scoreboard headline service; Brief and Scoreboard bundle composition remain follow-up work.
* [x] Focused Map, Matrix, Scoreboard, OpenAPI, Conditions, Range, and Forecast tests pass after the shared-boundary changes.
