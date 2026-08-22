# 0004 - map-workspace-presentation

Type: refactor
Branch: refactor/0160-frontend-api-architecture-refactor/0004-map-workspace-presentation
Base: merged `0003-workspace-state-architecture`
Source: `plan/0160-frontend-api-architecture-refactor/README.md`
Depends on: 0002, 0003

## Goal

* Reduce `MapWorkspace` to composition, route wiring, and feature-hook integration.
* Isolate map rendering, selection cards, constraint controls, and layout into typed presentation units.
* Preserve synchronized-map behavior, mobile behavior, and map deep links.

## Context

* `web/src/workspaces/MapWorkspace.tsx` is 1,371 lines and owns bootstrap loading, row derivation, route synchronization, camera sync, interactions, and layout.
* `GridMap`, `SidePanel`, `DetailCard`, and `CompareMap` already provide partial seams but receive a large controller prop surface.
* MapLibre lifecycle and dual-pane camera synchronization need imperative ownership distinct from product state.

## Approach

* Work in: `web/src/workspaces/MapWorkspace.tsx`, `web/src/components/map/*`, `web/src/components/panels/*`, new `web/src/features/map/*`.
* Make `MapWorkspace` compose `useMapBootstrap`, `useMapRows`, and `useConstraintSelection` from 0003; remove direct fetching and request-token refs.
* Extract a `MapRouteState` adapter for parsing/writing `view`, `data`, constraint, settlement-point, and shared-coordinate preserving links.
* Extract a `useSynchronizedMaps` adapter for MapLibre refs/listeners and keep it separate from selection state.
* Group render-only props into view models for the map panes, side panel, detail cards, and mobile drawer; avoid a new catch-all Map context unless descendants demonstrably need the same stable state.
* Move MapWorkspace-owned CSS from its render tree into colocated feature styles; retain dynamic fills/geometry as CSS properties.
* Preserve existing public component props with adapters while extracting units; remove adapters only after their in-branch call sites migrate.

## Acceptance

* [x] `MapWorkspace` no longer directly fetches API resources or implements camera listener wiring.
* [x] Forecast, market, compare, error, mobile, hover, pin, lock, and reach interactions behave as before.
* [x] Existing map URLs round-trip without dropping shared time coordinates or `autoPlay`.
* [x] Component tests cover panel-to-map selection propagation and background clear behavior.
* [x] `npm run build`, lint, and Map interaction tests pass from this branch without requiring a server change.
