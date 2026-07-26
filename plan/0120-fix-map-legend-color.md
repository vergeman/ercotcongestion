# 0120 - fix-map-legend-color

Type: fix
Branch: fix/0120-map-legend-color

## Goal

* Make map color domains and legend ticks follow the playback cursor's Central-time delivery day.
* Keep a single color meaning for metric maps while a constraint is being explored.
* Explain the map's aggregate-node markers: `H` for hub and `Z` for load zone.
* Verify the legend, map fills, hover focus, and constraint-panel cues remain consistent.

## Context

* The explorer currently derives congestion, LMP, forecast, and forecast-error scales once from every sample in the loaded playback window.
* Moving the playback scrubber changes the displayed data but not that window-wide color domain; an extreme value on another day can therefore mute the current day.
* Blue/red currently serves both signed metric views and the constraint reach's import/export role, even though those meanings can disagree in forecast-error and LMP views.
* Existing congestion scaling deliberately uses a robust percentile anchor rather than literal extrema, protecting ordinary nodes from a single scarcity outlier.

## Approach

* Work in: `web/src/workspaces/MapWorkspace.tsx`, `web/src/hooks/useExplorerSession.ts`, `web/src/lib/colors.ts`, and the map/constraint presentation components that consume signed SF colors.
* Entry point / primary change: derive palette statistics from cached samples whose timestamp shares the playback cursor's `America/Chicago` delivery date; pass those day-scoped stats to every relevant `GridMap` and `Legend`.
* Preserve the existing robust percentile normalization inside a day unless a separately approved product decision calls for literal daily minimum/maximum endpoints.
* Ensure forecast and realized panes that show the same quantity use the same daily scale, retaining their direct visual comparability.
* Give signed constraint reach/SF exploration a dedicated, labeled soft-magenta import / teal export palette distinct from congestion, LMP, and forecast-error metric ramps; apply it consistently to map focus, detail cards, and the Constraints panel.
* Add compact `H` / `Z` aggregate-node marker definitions to the map legend.
* Update nearby comments and legends so color meaning is explicit at the point of use.
* Do NOT touch: API payload contracts, cached playback data, constraint mathematics, or the matrix's established SF convention unless a follow-up explicitly scopes those surfaces.

## Acceptance

* [x] Moving the playback scrubber within one Central-time delivery day keeps each palette's color domain stable.
* [x] Crossing a Central-time day boundary recomputes congestion, LMP, forecast, and forecast-error legend ticks and node fills from that day's cached data.
* [x] A value from a different day in a multi-day loaded window cannot set the active day's palette anchor.
* [x] Forecast and realized panes retain a shared daily scale whenever comparable source data exists.
* [x] Constraint exploration uses an import/export palette that is visually and semantically distinct from metric-map gradients, with matching labels in the map, detail card, and Constraints panel.
* [x] Every map legend identifies `H` as a hub and `Z` as a load zone.
* [ ] `npm run lint` and `npm run build` pass in `web/`.
