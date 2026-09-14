# 0214 - Remove unused API routes and web service code

Type: refactor
Branch: refactor/0214-remove-unused-api-and-web-services

## Goal

* Remove API routes with no web consumer and their dead frontend request wrappers.
* Preserve internal service composition and all web-visible behavior.

## Context

* The web frontend is the only supported API consumer.
* `/map/summary` composes overview and metadata in-process; it does not call their HTTP routes.
* Brief uses progressive hero/details/standouts requests, not the retired monolithic brief response.

## Approach

### Commit 1 — Remove unused HTTP routes

* Work in: `api/routes/map.py`, `api/routes/analysis/{hero,brief,grading,catalog}.py`, `api/tests/`, `api/ROUTE_INVENTORY.md`, and affected schemas.
* Remove `GET /map/overview` and `GET /map/meta`; retain `aggregate.overview()` and `aggregate.meta()` for `/map/summary`.
* Remove `GET /analysis/hero` while retaining `/analysis/hero/latest`.
* Remove `GET /analysis/brief`, `GET /analysis/grade`, and `GET /analysis/essp`; retain service functions used by `/analysis/brief/hero`, `/analysis/brief/details`, and matrix services.
* Remove direct-route tests, OpenAPI expectations, inventory entries, and endpoint-only schemas/comments.
* Do NOT remove `/analysis/standouts`, `/healthz`, map interaction routes, matrix frame/vocabulary routes, or service functions still composed in another route.

### Commit 2 — Remove dead frontend API code

* Work in: `web/src/api/{brief,briefCache,matrix,matrixFrames,analysisNode,client}.ts` and affected types/tests.
* Remove `fetchBriefDay`, `fetchBriefDayCached`, `BriefDay`, and their compatibility-facade exports.
* Remove `fetchAnalysisEsspGroups` and its facade export.
* Remove unused cache-clear exports and `matrixFrameCacheKey` if no consumer remains after the route cleanup.
* Keep `fetchBriefStandouts` and `fetchBriefStandoutsCached`: `useBriefDay` uses them.
* Run TypeScript/lint checks and remove any resulting dead imports.

## Acceptance

* [x] Removed routes return 404 and no longer appear in OpenAPI or the route inventory.
* [x] `/map/summary` still returns overview and metadata; Brief hero/details and Matrix behavior remain unchanged.
* [x] The web build, lint, and API tests pass with no dead wrapper, type, cache, or import left behind.
* [x] A source search confirms no web request path targets a removed route.
