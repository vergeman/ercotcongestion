# 205-0004 - refactor MapWorkspace seams

Type: refactor
Branch: refactor/205-0004-map-workspace-seams

## Goal

* Reduce `MapWorkspace` to a route-level composition component without changing map behavior.
* Extract cursor-derived data, view-control rules, and pane presentation at natural ownership boundaries.
* Preserve the map selection/constraint interaction state machine until it has focused behavioral coverage.

## Context

* `web/src/workspaces/MapWorkspace.tsx` is 1,067 lines and currently owns route state, cursor data derivation, concurrent fetch lifecycle, node/constraint interaction, and the Forecast/Market/Error render trees.
* `SidePanel` is standalone and its two local state concerns do not merit a shared hook. Its input derivation is a better seam because it belongs to the map cursor, not to panel presentation.
* The node/constraint block coordinates deep links, route writes, hover-versus-lock precedence, reach and exposure requests, token invalidation, and a day-scoped reach cache. It is cohesive but not a low-risk move-only extraction today.
* The Forecast and Error panes repeat the same prediction map, overlay, legend, and detail-card wiring with mode-specific data/presentation differences.

## Approach

* Work in: `web/src/workspaces/MapWorkspace.tsx`; add focused modules under `web/src/features/map/` and/or `web/src/hooks/`; preserve the existing component and API contracts.
* Commit 1 — Extract cursor-scoped derived data:
  - Create `useMapCursorData` (name subject to local conventions) to own `cursorTs`, CT `deliveryDay`, preview status, `useMapRows`, forecast-error rows, conditions-cache lookup, network stats, and settlement-point decomposition.
  - Return a compact typed result consumed by panes and `SidePanel`; retain the current null/fallback semantics exactly, including forecast-only error rows and forecast/realized node counts.
  - Extract the abortable scorecard request into a small `useMapScorecard(deliveryDay, forecastRunId)` hook. It must clear or gate stale data so a fast scrub cannot show the prior delivery date's scorecard.
  - Keep ranked-constraints loading separate unless its fetch contract becomes shared; it is a selection concern, unlike cursor display data.
* Commit 2 — Extract view-control policy:
  - Create `useMapViewControls` for desktop/mobile rendered-view resolution, Error's congestion-only data-mode invariant, restoration of the prior data mode after Error, and the view-dependent constraint-overlay default.
  - Give the hook the existing route-state `view`/`dataMode` setters; return `renderedView`, `showConstraints`, `setShowConstraints`, `handleView`, and `handleDataMode` so `Header`, `Legend`, and pane composition retain their existing callers.
  - Preserve mobile's forced Forecast rendering while retaining the user's desktop selection, and do not move URL parsing/serialization out of `useMapRouteState`.
* Commit 3 — Extract pane presentation, not interaction ownership:
  - Add a `MapPanes` feature component (or `PredictionPane` plus `MarketPane` if its prop contract is clearer) to render Forecast, Market, and Error from typed pane configuration.
  - Factor the shared prediction behavior used by Forecast and Error: `GridMap` overlay callbacks, prediction `DetailCard`, constraint toggle wiring, and member ring. Express only intentional differences as config: rows/stats, data mode, error color/legend overrides, labels/count copy, and preview badge.
  - Keep `MapWorkspace` as the owner of interaction callbacks and state; pass an intentionally grouped `predictionInteractions`/`marketInteractions` object rather than moving request/effect logic into presentation components.
  - Preserve Compare's exact Forecast-left / Market-right composition and the distinct actual-pane DetailCard with drivers disabled.
* Commit 4 — Deliberately defer the risky interaction extraction:
  - Leave deep-link replay, pinned node/exposures, reach previews, constraint focus cache, hover/lock precedence, and request-token guards in `MapWorkspace` for this pass.
  - If a later refactor is desired, first add focused behavioral coverage, then extract that block as one `useMapSelectionController` hook rather than splitting its shared state over multiple hooks.
  - Do NOT touch: API request shapes, `useMapRouteState` URL format, `GridMap`/`DetailCard` behavior, `ConstraintPanel` behavior, map topology bootstrap, or visual product requirements.
* Comments: as hooks/panes are extracted, revise their comments to brief, plain-English intent — cut statistical jargon, over-explanation, and verbosity (power terminology is fine).

## Verification

* Run `npx tsc -b` in `web/` and `npm run lint`; compare any repository-wide hook warnings against the pre-refactor baseline.
* Manually smoke `/map` at desktop and mobile widths: Forecast/Market/Compare/Error transitions, LMP versus congestion restoration after Error, constraint-overlay defaults, scorecard updates while scrubbing days, Conditions values, and side-panel ranked constraints.
* Exercise each interaction path after pane extraction: settlement-point click/close, actual-pane click, constraint row hover/click, member hover/click, overview preview, background clear, and inbound `sp`/constraint deep links.

## Acceptance

* [x] `MapWorkspace` no longer implements cursor-data transformations or the scorecard fetch lifecycle inline. — `useMapCursorData` + `useMapScorecard`.
* [x] View/data-mode and constraint-overlay transition rules have one tested/documented owner and preserve mobile behavior. — `useMapViewControls` (mobile still renders Forecast).
* [x] Forecast and Error reuse one prediction-pane presentation path; Market remains correctly distinct and Compare remains a Forecast/Market split. — shared `PredictionPane`, standalone `MarketPane`, `CompareMap` split unchanged.
* [x] Node/constraint interaction semantics, request cancellation/token guards, and deep links are behaviorally unchanged. — interaction controller left in `MapWorkspace` (commit-4 deferral); panes receive grouped `predictionInteractions`/`marketInteractions`.
* [x] `SidePanel` remains standalone; no speculative SidePanel hook is introduced.
* [x] Comments on extracted hooks/panes are brief plain English — no statistical jargon, over-explanation, or verbosity.
* [x] TypeScript and ESLint meet the project's existing baseline, and manual map smoke checks pass. — `tsc -b` clean, `eslint .` byte-identical to baseline (27 problems, 0 in new files), `vite build` succeeds; interactive `/map` smoke confirmed after loading the branch onto master.
