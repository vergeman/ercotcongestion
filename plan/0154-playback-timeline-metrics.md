# 0154 - playback-timeline-metrics

Type: feat
Branch: feat/0154-playback-timeline-metrics

## Goal

* Show forecast congestion, ERCOT congestion, and ERCOT system λ in playback.
* Keep the legend aligned with the delivery-hour label.

## Context

* The timeline previously showed only realized absolute congestion.
* Forecast congestion and realized SPP data already load with the playback window.
* System λ must be sent exactly, not reconstructed from rounded congestion.

## Approach

* [x] Add nullable `system_lambda` to compact `/ercot_range` entries and cache it.
* [x] Build per-hour forecast/realized `Σ|nodal congestion|` series in `useExplorerSession`.
* [x] Draw independently normalized forecast, ERCOT congestion, and ERCOT system-λ paths in `TimelineSparkline`.
* [x] Move the legend to the top metadata row; keep the chart track bottom-aligned.
* [x] Add capitalized labels and a normalization tooltip.
* Do NOT add an LMP series or a system-λ forecast.

## Acceptance

* [x] Playback shows all three labeled series with gaps for unavailable data.
* [x] Forecast and ERCOT congestion use separate maxima; system λ uses its observed min/max.
* [x] `/ercot_range` returns exact system λ and its focused API test passes.
* [x] TypeScript no-emit and `TimelineSparkline` lint pass.
