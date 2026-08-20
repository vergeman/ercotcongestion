# 0152 - map-extrema-scale-and-aggregate-legend

Type: fix
Branch: fix/0152-map-extrema-scale-and-aggregate-legend

## Goal

* Make rare, extreme signed congestion values visually and numerically distinct from the daily P90 core on map legends.
* Keep ordinary congestion differences readable without letting one scarcity node flatten the map.
* Render Hub and Load zone legend keys with the same theme-aware marker treatment as the map.

## Context

* Congestion uses a cursor-day P90 anchor (`p_high`), but its short rational tail asymptotes above that anchor while the legend labels P90 as the bar endpoint.
* At `RHESS2_ESS1`, `2025-02-20T13Z`, realized congestion is near $6,000 while the daily anchor is about $90, so the current key conceals the magnitude gap.
* Aggregate map labels are near-black by design because they sit over a colored marker; the legend applies that color to an unfilled outline, which disappears in dark mode.

## Approach

* Work in: `web/src/lib/colors.ts`, `web/src/components/map/Legend.tsx`, `web/src/components/map/GridMap.tsx`, `web/src/workspaces/MapWorkspace.tsx`, and focused frontend tests if a test harness is added/available.
* Entry point / primary change: `computeCongestionStats`, `normalizeCongestion`, and the congestion branch of `Legend`.
* Preserve the CT-delivery-day P90 as the robust core anchor, but retain the observed positive and negative daily extrema separately in `CongestionStats`.
* Replace the unbounded rational tail with a bounded log tail per sign: map the P90 core to a labeled interior stop and map that sign's observed daily extreme to the color endpoint. When no material tail exists, let the core reach the endpoint.
* Add explicit interior P90 ticks and signed endpoint-extrema ticks to the congestion/error legend; position histogram bins using the same normalization as node fills. Do not label the endpoint as P90 when it represents an extreme.
* Use the same scale contract for realized congestion, forecast congestion, and forecast error, preserving each view's palette and existing forecast/market comparison rules.
* Refactor `AggregateMark` into the map’s visual grammar: a colored circular Hub marker and colored diamond Load zone marker, each with the dark-on-fill `H`/`Z` label used by `aggregate-labels`. Feed its representative fill from the active legend palette, including the forecast-error override, and resolve it again on theme changes.
* Keep selection, hover, constraint-reach/SF colors, LMP normalization, API payloads, and playback loading out of scope.

## Acceptance

* [ ] At `sp=RHESS2_ESS1&t=2025-02-20T13Z&ws=2025-02-19T18Z&we=2025-02-21T18Z&view=market&data=congestion`, the realized ~$6,000 value has the positive endpoint color and the legend shows both the approximately +$90 core stop and the approximately +$6,000 endpoint.
* [ ] Typical values at or below the daily P90 retain visible signed contrast, while values between P90 and the observed extreme receive distinct progressively deeper colors.
* [ ] Negative and positive tails use their own observed extrema; absent or non-material tails do not create misleading endpoint labels or divide-by-zero normalization.
* [ ] Forecast and error congestion legends/fills follow the same core-plus-extrema scale while retaining their existing labels and palette semantics.
* [ ] In dark and light themes, Hub is a filled circle with `H` and Load zone is a filled diamond with `Z`; both remain legible and match the map marker/label treatment.
* [ ] `npm run lint` and `npm run build` pass in `web/`.
