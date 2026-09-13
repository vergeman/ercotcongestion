# 0211 - Market modeled footprints

Type: feat
Branch: feat/0211-market-modeled-footprints

## Goal

* Offer the regression-derived constraint-footprint overlay on the ERCOT Market map.
* Preserve a clear distinction between realized DAM values and modeled structure.

## Context

* `GridMap` and `/map/*` already support overview hover, reach, and realized DAM μ.
* `MarketPane` currently omits that wiring; Forecast and Error own it exclusively.
* A visible footprint must not imply that ERCOT published it or that it bound this hour.

## Approach

* Work in: `web/src/workspaces/MapWorkspace.tsx`, `web/src/features/map/MarketPane.tsx`, `web/src/features/map/mapPaneTypes.ts`, `web/src/features/map/useMapViewControls.ts`, `web/src/components/map/detail/ReachBody.tsx`, and relevant web tests.
* Pass the existing overview, toggle, reach/focus state, and constraint-hover/select callbacks to the Market pane; keep Market node cards scoped to realized SPP/congestion.
* Keep the overlay off by default on entering Market, expose its legend control there, and label it `Modeled constraint footprints` with explanatory copy.
* On Market constraint selection, render ERCOT DAM shadow price and realized `−SF × μ` contribution; label forecast values separately if both are shown.
* Clear constraint reach/focus on a Market node or background click, matching the Forecast interaction model.
* Do NOT touch: forecast generation, SF fitting, ERCOT ingestion, or map API contracts unless a missing realized-value field is demonstrated.

## Acceptance

* [ ] Market mode can toggle and hover/select modeled footprints without changing its realized node coloring.
* [ ] Market constraint detail uses actual DAM μ/contribution when published and never labels it as forecast.
* [ ] The overlay is disabled by default in Market and identifies itself as regression-derived.
* [ ] Focused interaction/UI tests cover Market overlay visibility, selection cleanup, and realized-value labels.

## Follow-up refactor

* Consolidate Forecast, Market, and Error map panes behind one side-aware pane component.
* Remove the parallel pane contracts and superseded pane components.
* Verify TypeScript and lint after the behavior-preserving consolidation.
