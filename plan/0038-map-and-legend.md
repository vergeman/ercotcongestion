# B2 - map-and-legend

Type: refactor
Branch: refactor/0038-map-and-legend

## Goal

* Rewire `web/src/components/map/GridMap.tsx` to switch on the four new `ViewMode` values using `modeledCongestionColor` / `bindingProximityColor` / `computeCongestionVsBasisRank` from 0037.
* Rewrite `web/src/components/map/Legend.tsx` — diverging legend for `modeled_congestion` (zero-centered, export/import ticks), sequential [0, 1] legend for `binding_proximity`, updated header for `congestion_vs_basis`.
* Relabel and reorder the four view buttons in `web/src/components/layout/Header.tsx` — `LMP | Modeled Congestion | Binding Proximity | Congestion vs Basis`.

## Context

* Depends on 0037 (`refactor/0037-types-and-scales`) for the renamed `ViewMode`, color functions, and anchor exports.
* Playable in isolation once 0037 is in — the map + legend + header can render against a Sprint-0 sample DB running through the 2B endpoints.
* PTDF hover halos (`halo_sign`, ice-vs-orange) already preserve sign; they now align with the diverging `modeled_congestion` palette. Do NOT relabel halos as N-1 (per sprint2-handoff.md §4.3).
* `App.tsx` `useState<ViewMode>` default flips to `"modeled_congestion"` here; the full `zStats` deletion + sparkline rewire happens in 0039.

## Approach

* Work in: `web/src/components/map/GridMap.tsx`, `web/src/components/map/Legend.tsx`, `web/src/components/layout/Header.tsx`, `web/src/App.tsx` (default view + zStats prop removal only)
* `web/src/components/map/GridMap.tsx`:
  * Imports: drop `fragilityColor`, `fragilityZ`; add `modeledCongestionColor`, `normalizeModeledCongestion`, `bindingProximityColor`, `normalizeProximity`, `computeCongestionVsBasisRank`, and their anchor consts.
  * Switch on `viewMode`:
    * `"modeled_congestion"`: build the normalized map from `bus.modeled_congestion` across the visible frame; paint via `modeledCongestionColor`.
    * `"binding_proximity"`: paint each bus via `bindingProximityColor(normalizeProximity(bus.binding_proximity))`.
    * `"congestion_vs_basis"`: call `computeCongestionVsBasisRank` (signed on both inputs) and paint via existing `rankDeltaColor`.
    * `"lmp"`: unchanged.
  * Drop the `zStats` prop from `GridMapProps` and its usage; delete any `fragility_z` code path.
  * Add a one-line comment on the halo block: "halo sign aligns with the diverging modeled_congestion palette".
* `web/src/components/map/Legend.tsx`:
  * Replace `isFragility` / `isZ` branches with `isModeledCongestion` / `isBindingProximity` / `isCongestionVsBasis`.
  * Diverging legend for `modeled_congestion`: center tick "0", left tick "export (−)", right tick "import (+)"; include the window-percentile anchor value as the extreme tick label.
  * Sequential legend for `binding_proximity`: ticks at 0, 0.5, 0.9, 1.0; caption "0 slack, 1 binding".
  * `congestion_vs_basis` header: "Δ Rank (modeled congestion − basis)"; keep teal/purple gradient block.
  * `lmp` legend unchanged.
* `web/src/components/layout/Header.tsx`:
  * Rewire the four buttons — labels: "LMP", "Modeled Congestion", "Binding Proximity", "Congestion vs Basis". Reorder to that sequence.
  * Update the four `viewMode === "..."` active-state checks.
* `web/src/App.tsx`:
  * Line 41: default `useState<ViewMode>("modeled_congestion")`.
  * Delete `zStats` state, the `computeBusZStats` import + call, and the `zStats={zStats}` prop passed to map + panel (lines ~270, ~291). Full sparkline rewire is 0039; leave the `entry.meta.fragility_total` read alone here — it will produce a type error the sparkline branch resolves.
* Do NOT touch: `DetailCard.tsx`, `StatsPanel.tsx`, `ValidationPanel.tsx`, `TimelineSparkline.tsx`, `events.ts` (0039-0041 scope).

## Acceptance

* [x] `grep -rn "fragility\|frag" web/src/components/map/ web/src/components/layout/Header.tsx` returns 0 hits.
* [ ] All four `ViewMode` cases render without console errors when swept on a Sprint-0 snapshot. _(needs dev-server run)_
* [ ] Modeled-congestion view on a DFW summer-peak snapshot shows both red (import, north_central) and blue (export, west) buses — sign visible. _(needs dev-server run)_
* [ ] Binding-proximity view shows the L15xx/L20xx-adjacent DFW buses in the top-band color; slack corridors dim. _(needs dev-server run)_
* [x] Legend updates correctly on view swap; no stale "Δ Rank (fragility − |basis|)" copy. _(code updated; visual pending)_
* [x] Header shows the four buttons in the new order with new labels; active-state highlighting tracks the selected view.
* [x] `App.tsx` no longer references `zStats` or `computeBusZStats`.

Note: added `mcStats` (window-percentile `ModeledCongestionStats`) in `App.tsx`, plumbed through to `GridMap` + `Legend` — mirrors `lmpStats` architecture; required by the Legend anchor tick. `fragility_total` sparkline reads in `App.tsx` intentionally left broken for 0039.
