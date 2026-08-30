# 0001 - Authoritative domain schemas

Type: refactor
Branch: refactor/0180-authoritative-api-schemas

## Goal

* Make `api/schemas/` the physical owner of all Pydantic API response schemas.
* Retain `api/models.py` as a temporary compatibility re-export module.

## Context

* `api/models.py` contains 1,234 lines and 74 response classes.
* Domain schema modules already exist but only import and re-export from `models.py`.
* Production routes already import through domain-specific schema modules; a few tests still import `models` directly.

## Approach

* Work in: `api/models.py`, `api/schemas/`, and `api/tests/`.
* Entry point / primary change: replace schema façade imports with the domain-owned class definitions.
* Move classes by response ownership: analysis/Brief, forecast plus ERCOT range, map, matrix, Scoreboard, Conditions, and shared bootstrap status.
* Keep cross-domain schema imports one-directional: `common` owns shared primitives; `map` may import the Scoreboard headline type; do not recreate shared models in multiple modules.
* Replace `api/models.py` with explicit compatibility imports/re-exports after the moves, then migrate in-repository test imports to owning schema modules.
* Compare generated OpenAPI before and after; preserve component names, fields, defaults, and unions exactly.
* Do NOT touch: route decorators, public response contracts, or database/compute models.

## Acceptance

* [ ] No Pydantic response class is defined in `api/models.py`; it is only a documented compatibility shim.
* [ ] Each `api/schemas/<domain>.py` defines the schemas its routes and services consume.
* [ ] `api/tests/test_openapi.py` and focused API tests pass with identical OpenAPI component names and paths.
* [ ] No production module imports a schema from `models`.
