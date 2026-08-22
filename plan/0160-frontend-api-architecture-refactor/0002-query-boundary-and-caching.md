# 0002 - query-boundary-and-caching

Type: refactor
Branch: refactor/0160-frontend-api-architecture-refactor/0002-query-boundary-and-caching
Base: merged `0001-api-contracts`
Source: `plan/0160-frontend-api-architecture-refactor/README.md`
Depends on: 0001 for the target availability contract

## Goal

* Replace repeated request boilerplate with a typed web HTTP boundary.
* Colocate query-key construction and cache policy with each feature resource.
* Make cancellation, unavailable data, and stale responses predictable.

## Context

* `web/src/api/client.ts` contains repeated fetch/status/JSON logic for every route.
* Brief, Matrix, prefetch, and map-interaction flows each implement partial cache or stale-response behavior independently.
* The app needs bounded local caches, not necessarily a global query-library migration.

## Approach

* Work in: `web/src/api/client.ts`, `web/src/api/{briefCache,matrixFrames,prefetch,analysisNode}.ts`, new `web/src/api/http.ts`, and feature-local `queries.ts` modules.
* Define a typed request result/error policy that distinguishes abort, transport failure, invalid payload, and API-unavailable response.
* Split the catch-all client by feature (`map`, `matrix`, `brief`, `scoreboard`, `explorer`) and colocate typed query parameter builders there.
* Introduce one bounded promise/result cache primitive with explicit key, max size, invalidation, optional TTL, and abort ownership; migrate existing caches incrementally.
* Retain `prefetchWindow` as an orchestration layer, not a general cache API.
* Do NOT change endpoint payload shapes here; consume the contracts delivered by 0001.
* Migrate one feature client at a time and preserve the legacy exported client facade until all in-repo callers have moved; this branch must be safe to deploy against either API contract form.

## Acceptance

* [x] Feature query functions do not duplicate HTTP status-to-state conversion.
* [x] Cache keys include all parameters that affect a response, including date/run/basis/rank.
* [x] Aborted or stale requests cannot replace newer feature state.
* [x] Tests cover deduplication, eviction/invalidation, 503-unavailable, and abort behavior.
* [x] `npm run build` and lint pass with the old UI behavior intact after the query-boundary migration.
