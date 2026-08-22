# 0003 - workspace-state-architecture

Type: refactor
Branch: refactor/0160-frontend-api-architecture-refactor/0003-workspace-state-architecture
Base: merged `0002-query-boundary-and-caching`
Source: `plan/0160-frontend-api-architecture-refactor/README.md`
Depends on: 0002 for feature query ownership

## Goal

* Keep only URL-synchronized explorer state in shared context.
* Move feature data loading and coupled interaction transitions into hooks and reducers.
* Preserve Map/Matrix time navigation and every existing deep-link contract.

## Context

* `ExplorerContext` correctly shares time/session state, while Map and Brief each own many independent fetch and interaction atoms.
* Map’s hover/lock/pin/reach transitions are interdependent; Brief’s progressive loading and selection state are interdependent.
* Request-version and boolean liveness guards are scattered through controllers.

## Approach

* Work in: `web/src/hooks/{useSharedExplorer,useExplorerSession}.tsx`, `web/src/workspaces/{MapWorkspace,MatrixWorkspace}.tsx`, `web/src/pages/{BriefPage,ScoreboardPage}.tsx`, and new feature hooks.
* Retain `ExplorerProvider` as the owner of cursor, URL synchronization, prefetch session, and scrubber state. Do NOT place Brief, Scoreboard, or Map selection data in it.
* Create `useMapBootstrap`, `useMapRows`, `useConstraintSelection`, and `useMapInteractionQueries`; encode hover/locked/focused/pinned/reach transitions in a reducer with explicit actions.
* Create `useBriefDay` to own day resolution, hero shell, progressive detail loading, retries, and request cancellation; use a reducer for its dependent transitions.
* Create `useScoreboard` for server state and a small controls reducer for metric/group/horizon UI state.
* Extract duplicated media-query behavior into `useMediaQuery`; migrate effect cleanup to AbortController/query cancellation where possible.
* Migrate feature hooks behind the existing workspace/page render contracts; do not combine this branch with structural component moves from 0004–0007.

## Acceptance

* [x] Context updates do not include feature-specific data or selection state.
* [x] Reducer tests cover Map lock/hover/clear and Brief day/retry/loading transitions.
* [x] Map and Matrix retain synchronized `t/ws/we/span/run` behavior across navigation.
* [x] Feature hooks own request cleanup; pages do not directly coordinate stale-response guards.
* [x] The refactored state layer deploys with identical rendered component contracts and passing web build/lint checks.
