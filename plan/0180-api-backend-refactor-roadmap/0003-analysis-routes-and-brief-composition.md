# 0003 - Analysis routes and Brief composition

Type: refactor
Branch: refactor/0182-analysis-routes-and-brief-composition

## Goal

* Split the Analysis HTTP surface into focused route modules.
* Move Brief assembly to a non-route service that composes Analysis services directly.

## Context

* The existing Analysis router mixes 13 independently useful endpoints with Hero and bundled Brief endpoints.
* `get_brief_hero_shell`, `get_brief_hero_stats`, and the day bundle call `get_hero` or sibling decorated handlers directly.
* Direct handler calls make dependency defaults, tests, and router moves part of internal composition.

## Approach

* Work in: `api/routes/analysis/` (or a transitional `api/analysis_routes/` package), `api/services/analysis/`, `api/main.py`, and Analysis tests.
* Entry point / primary change: create separate routers for node/catalog, insights, grading, hero, and Brief while retaining the `/analysis` prefix and tag.
* Build `services/analysis/brief.py` from the prior branch's callable services; own section caches, neighbor-day lookup, parallel composition, and soft-fail policy there.
* Replace all route-to-route calls with service calls. Route handlers should only resolve FastAPI inputs and delegate.
* Include the new routers from `main.py` with the same root-mounted paths and preserve their OpenAPI operation behavior.
* Update monkeypatch-heavy tests to patch service collaborators or explicit router module imports, not endpoint-to-endpoint calls.
* Do NOT touch: Brief payload shape, progressive-loading endpoints, cache lifetime/keys, or client-visible unavailable reasons.

## Acceptance

* [ ] No Analysis route handler invokes another decorated Analysis route handler.
* [ ] All existing `/analysis/*` paths, tags, parameters, and response schemas remain present in OpenAPI.
* [ ] Brief sections still share the exact prior run/day/horizon resolution and availability rules.
* [ ] Focused Analysis and OpenAPI tests pass.
