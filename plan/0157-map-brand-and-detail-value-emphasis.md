# 0157 - map brand and detail value emphasis

Type: feat
Branch: feat/0157-map-brand-and-detail-value-emphasis

## Goal

* Make the ERCOT Stress brand in the shared header navigate to the root route without retaining query parameters.
* Rename the map view control from “Market” to “ERCOT”.
* Make the DetailCard metrics for the active Forecast or ERCOT source easy to scan.

## Context

* `HeaderNav` currently renders the bolt and “ERCOT Stress” title as non-interactive spans; its primary navigation intentionally carries shared time query parameters.
* The map view state uses `market` internally, even though its rendered market pane and data describe ERCOT DAM values.
* `DetailCard` always displays the forecast, realized, error, predicted-LMP, and DAM-LMP decomposition, but receives no view context to distinguish the active source.

## Approach

### Commit 1 — make the shared map chrome use the requested terminology and root link

* Work in: `web/src/components/layout/HeaderNav.tsx` and `web/src/components/layout/Header.tsx`.
* Replace the bolt/title brand spans with one accessible root anchor around the existing visual brand. Route it to `/` with no search string, using ordinary router navigation for an unmodified primary click while preserving normal browser behavior for modified clicks.
* Add focused brand-link styling so its current appearance, hover affordance, mobile sizing, and header layout remain intact.
* Keep the existing `coord` propagation only on primary navigation links; clicking the brand must discard all query parameters, including time, selection, and view state.
* Change only the visible `market` entry in `VIEWS` from “Market” to “ERCOT”; retain the `MapView` key, URL contract, and data fetching behavior as `market`.

### Commit 2 — give DetailCard explicit source context and emphasize active values

* Work in: `web/src/components/map/DetailCard.tsx` and `web/src/workspaces/MapWorkspace.tsx`.
* Add a narrow DetailCard display-context prop (forecast versus ERCOT/realized) and pass it at every map card mount: forecast and error/prediction cards select forecast values; the market/actual card selects ERCOT values. In Compare, each pane’s card uses its own source context.
* Teach `Row`/`SpBody` to preserve normal styling for the active source metrics and apply a subdued class to the companion metrics, leaving labels and unavailable values structurally unchanged.
* In forecast context, fade Realized Congestion and DAM LMP; in ERCOT context, fade Forecast (P50) Congestion, Forecast Error, and Predicted LMP. Preserve all five rows and their existing formatting in either context.
* Add the subdued companion-metric style locally with the existing DetailCard typography rules; do not alter driver rows, reach cards, map palettes, or the underlying `market`/forecast data calculations.

## Acceptance

* [x] The bolt/ERCOT Stress brand is keyboard-accessible and navigates to exactly `/` without carrying any current query parameters; the existing primary navigation continues to preserve only its shared time coordinate.
* [x] The map view toggle visibly says Forecast, ERCOT, Compare, and Error, while an ERCOT selection still uses the existing `market` URL/state behavior.
* [x] Forecast and prediction/error DetailCards keep Forecast (P50) Congestion, Forecast Error, and Predicted LMP at normal emphasis while fading Realized Congestion and DAM LMP; ERCOT DetailCards do the inverse, including the respective panes of Compare.
* [x] `tsc --noEmit -p web/tsconfig.app.json` and focused lint pass; repository-wide lint remains blocked by pre-existing React hook-rule errors in `MapWorkspace.tsx`.
