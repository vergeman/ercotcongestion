# 0160 - frontend API architecture refactor

Type: refactor
Branch: refactor/0160-frontend-api-architecture

## Goal

* Establish stable resource-oriented API contracts and a typed web query boundary.
* Isolate shared explorer state from feature-specific server and interaction state.
* Split page controllers into testable feature units without changing visible behavior.

## Sequence

1. `0001-api-contracts.md` — classify and consolidate server routes.
2. `0002-query-boundary-and-caching.md` — standardize web requests, availability, cancellation, and caching.
3. `0003-workspace-state-architecture.md` — introduce feature hooks/reducers and narrow context ownership.
4. `0004-map-workspace-presentation.md` — split Map presentation after its state boundary exists.
5. `0005-matrix-workspace-presentation.md` — split Matrix presentation after query ownership is stable.
6. `0006-brief-page-presentation.md` — split Brief sections after `useBriefDay` owns progressive loading.
7. `0007-scoreboard-page-presentation.md` — split Scoreboard sections and separate live/backtest reads.

## Branch and rollout rule

* Implement and merge the plans in numeric order. Each numbered branch starts from the prior numbered plan after it is merged; `0001` starts from `main`.
* Branch names are `refactor/0160-frontend-api-architecture-refactor/000N-<plan-slug>`.
* Every branch must be deployable by itself: retain backwards-compatible API behavior, preserve existing routes/deep links, avoid required coordinated deploys, and run the touched API/web test and build checks before merge.
* Feature flags or compatibility adapters belong in the earlier branch when a later branch needs a new contract. Remove them only in a subsequent independently deployable plan.

## Constraints

* Preserve public API compatibility until route consumers are audited and migrated.
* Preserve URL deep links and the Map/Matrix shared time cursor.
* Land each plan independently with behavior and accessibility tests for the touched surface.
