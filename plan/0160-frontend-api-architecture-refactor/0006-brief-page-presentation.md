# 0006 - brief-page-presentation

Type: refactor
Branch: refactor/0160-frontend-api-architecture-refactor/0006-brief-page-presentation
Base: merged `0005-matrix-workspace-presentation`
Source: `plan/0160-frontend-api-architecture-refactor/README.md`
Depends on: 0002, 0003

## Goal

* Split the Brief page into independently rendered hero, evidence, navigation, and detail sections.
* Make progressive day loading and retry behavior a single feature-state contract.
* Preserve visual sequence, adjacent-day navigation, and Map handoffs.

## Context

* `web/src/pages/BriefPage.tsx` is 2,162 lines, including section rendering, multiple fetch effects, local request state, selection logic, and page CSS.
* `BriefDetailPanel`, `HeroMapPreview`, and `BriefFootprintMap` are existing child seams; their parent still owns large untyped prop/state coordination.
* Brief intentionally paints hero content before secondary evidence, so one monolithic load state would regress perceived performance.

## Approach

* Work in: `web/src/pages/BriefPage.tsx`, `web/src/components/brief/*`, `web/src/api/briefCache.ts`, new `web/src/features/brief/*`.
* Move all API coordination into `useBriefDay` from 0003. Return a typed view model that distinguishes hero-shell loading/error, progressive section availability, stale day responses, and retry actions.
* Extract `BriefDayControls`, `BriefHero`, `BriefEvidence`, `BriefGrade`, and `BriefDetails` composition components; preserve existing specialized visual components beneath them.
* Move day/cursor selection and Map-link construction into pure Brief route/selection helpers, with focused tests for CT delivery-day bounds and `autoPlay` links.
* Move the page-level Brief CSS into a colocated stylesheet or feature style entry; retain per-scale positioning as custom properties/inline values.
* Do NOT replace progressive requests with a blocking `/analysis/brief`-only fetch; use the composite endpoint selectively where it improves cold-entry behavior.
* Keep the existing endpoint usage and route parameters compatible throughout this branch; presentation extraction must not require a simultaneous API release.

## Acceptance

* [x] Changing delivery day cannot show a stale hero or details from a prior day.
* [x] Hero shell renders independently of delayed detail sections and presents retry/error states consistently.
* [x] Adjacent-day controls, event selection, metric explanations, and Map deep links keep existing behavior.
* [x] `BriefPage` is a composition module rather than the owner of fetch effects and every section’s markup/style.
* [x] `npm run build`, lint, Brief behavior tests, and Map-handoff route tests pass from this branch alone.
