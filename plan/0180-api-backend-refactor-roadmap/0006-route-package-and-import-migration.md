# 0006 - Route package and import migration

Type: refactor
Branch: refactor/0185-api-route-package-imports

## Goal

* Consolidate thin HTTP modules under an explicit `api.routes` package.
* Convert the API from top-level `/api` imports to package-qualified imports.

## Context

* The container currently puts `/api` directly on `PYTHONPATH`, so routes import `db`, `schemas`, and `services` as top-level modules.
* That convention makes physical route subpackages awkward and risks duplicate module instances during a partial move.
* This migration should occur only after the service extractions leave routes small and independently testable.

## Approach

* Work in: `api/main.py`, `api/routes/`, `api/schemas/`, `api/services/`, `api/tests/`, `Dockerfile`, and `docker-compose.yml`.
* Entry point / primary change: make `api` the importable package and use `api.routes`, `api.schemas`, `api.services`, `api.db`, and `api.config` consistently.
* Move the thin route modules into `api/routes/`, retaining domain subpackages already introduced for Analysis and Map; update `main.py` router imports.
* Change runtime and test `PYTHONPATH`/module invocation deliberately so there is one canonical import path; remove compatibility aliases only after all imports and monkeypatch targets are migrated.
* Run the complete API suite and validate that FastAPI OpenAPI paths/tags remain root-mounted.
* Do NOT touch: external API URLs, compute package imports, database configuration values, or unrelated web imports.

## Acceptance

* [x] Every API production import resolves through the `api` package; no duplicate top-level route/schema/service modules remain.
* [x] `api.main:app` is the documented and containerized application entry point.
* [x] All API tests use package-qualified imports and pass without import-order dependence.
* [x] OpenAPI paths and response contracts are byte-for-byte equivalent apart from irrelevant schema ordering.
