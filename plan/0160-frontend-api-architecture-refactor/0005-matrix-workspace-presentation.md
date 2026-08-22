# 0005 - matrix-workspace-presentation

Type: refactor
Branch: refactor/0160-frontend-api-architecture-refactor/0005-matrix-workspace-presentation
Base: merged `0004-map-workspace-presentation`
Source: `plan/0160-frontend-api-architecture-refactor/README.md`
Depends on: 0002, 0003

## Goal

* Separate Matrix frame loading, sidebar vocabulary, route selection, basis calculation, and stage rendering.
* Keep the matrix rectangle contract and Map handoff unchanged.
* Reduce `MatrixWorkspace` to a feature composition layer.

## Context

* `web/src/workspaces/MatrixWorkspace.tsx` owns a cached frame, multiple secondary queries, URL state, filtering, basis work, and its page-level style block.
* The sidebar, grid, legend, read detail, and basis panel are already components but depend on controller-owned state.
* `/matrix/frame` and the analysis vocabulary endpoints have distinct cache and cancellation needs.

## Approach

* Work in: `web/src/workspaces/MatrixWorkspace.tsx`, `web/src/components/matrix/*`, `web/src/api/matrixFrames.ts`, new `web/src/features/matrix/*`.
* Extract `useMatrixRouteState` for parse/serialize/default selection and pins, preserving the shell’s shared coordinate merge.
* Extract `useMatrixFrame`, `useMatrixVocabulary`, and `useMatrixBasis`; each returns typed loading/unavailable/error state and owns cancellation.
* Keep client-side filtering/sorting in a pure selector module and give `MatrixSidebar` a narrow data/action contract.
* Create explicit stage view models for `MatrixGrid`, `MatrixReadDetail`, `MatrixBasisPanel`, and mobile index; move component CSS out of render trees.
* Do NOT alter the `/matrix/frame` response rectangle, matrix math helpers, or the Map deep-link semantics in this refactor.
* Keep existing Matrix component props available through local adapters during the move so the completed branch needs no coordinated server or Map release.

## Acceptance

* [x] Matrix frame, vocabulary, and basis requests are independently cancellable and testable.
* [x] Search, filters, pins, selected row/column, mobile index, and route state behave identically.
* [x] Matrix-to-Map links retain the selected entity and shared explorer coordinate.
* [x] The workspace no longer mixes query implementation, selectors, and stage markup in one module.
* [x] `npm run build`, lint, and Matrix route/deep-link tests pass from this branch alone.
