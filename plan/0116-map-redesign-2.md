# 0116 - map-redesign-2

Type: refactor
Branch: refactor/0116-map-redesign-2

## Goal

* Refine the map interaction and sidebar presentation.

## Context

* Follow-up map/UI polish work on the forecast and constraint views.

## Approach

* Completed branch tasks:
  * [x] Replaced GTC halos and the purple bezier with a centroid glyph, minimal line, and refined popover interaction.
  * [x] Unified map tooltip and click behavior, including dual-map DetailCard handling and stale-request protection.
  * [x] Simplified DetailCard content, added shift-factor type/color indicators, and moved redundant readouts to the sidebar.
  * [x] Renamed legacy modeled-congestion labels to straightforward congestion terminology.
  * [x] Added ERCOT total load to the SPP range response and displayed it first in Network statistics.
  * [x] Reorganized sidebar statistics, placing Forecast Run with the rolling backtest score summary.
  * [x] Removed redundant tooltip UI and cleaned up date-picker/sidebar presentation.

## Acceptance

* [x] Focused API tests pass in Docker Compose.
* [x] Frontend production build passes in Docker Compose.
