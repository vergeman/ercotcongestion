# 0057 - ercot-pane-hover-detailcard

Type: feat
Branch: feat/0057-ercot-pane-hover-detailcard

## Goal

* Wire hover + click on the ERCOT (right) pane so an SP feature raises a DetailCard parallel to the model side's bus card.
* Show SP-shaped fields: `sp_id`, `sp_type`, `load_zone`, `cluster_id`, `congestion`, `DAM SPP`.
* Anchor the ERCOT card inside the right pane so it doesn't collide with the model-side card in split mode.

## Context

* The right pane (`web/src/App.tsx`) is a second `GridMap` fed with `spTopology` (SP features aliased to `bus_id`) and `ercotBuses` (SP congestion + SPP reshaped as `BusState`). Its four interaction callbacks were stubbed to `() => {}`.
* SP features carried only `sp_id`, `sp_type`, `cluster_id`, `best_corr`; no `load_zone`. No SP → weather_zone lookup exists — omitted from scope.
* SP names encode LZ via prefix for `LZ_*` / `HB_*`; OTHER/RN patterns are ambiguous, so those get `load_zone: null`.
* `ercotBuses[i].lmp` already carries DAM SPP from `getErcotSppCached` — no API work needed to surface it.

## Approach

* **Step 1 — SP metadata** (`api/services/topology_builder.py`):
  * `_sp_load_zone_from_name`: `LZ_XXX` → `xxx`; `HB_XXX` → `xxx_hub`; else `None`.
  * `_settlement_points_feature_collection` emits `load_zone` per feature and logs `SP load_zone tagged N/M via name prefix`.
  * `_cache_is_current` invalidates SP-featured caches missing `load_zone`.

* **Step 2 — SP DetailCard body** (`web/src/components/map/DetailCard.tsx`):
  * `HoveredSp` interface: `spId`, `props`, `spState: { congestion, spp } | null`.
  * `SpBody` renders: `SP Type`, `Load Zone`, `Cluster` (only if present), `Congestion` (signed `$/MWh`), `DAM SPP` (`$/MWh`). Nulls render as `—`.
  * `Props` extended with optional `hoveredSp` / `pinnedSp`. SP takes precedence (pinned > hover) when passed; bus/line stacks stay intact when SP is absent.

* **Step 3 — wire right pane** (`web/src/App.tsx`):
  * `hoveredSp` / `pinnedSp` state parallel to bus state (kept separate so both panes can display cards simultaneously).
  * `handleSpHover`, `handleSpClick`, `handleClearPinnedSp`; `spStateFor(spId)` reads `{ congestion: row.modeled_congestion, spp: row.lmp }` from `ercotBuses`. A freshness effect re-hydrates the pinned SP as the scrub index advances.
  * Right-pane `GridMap` uses the new handlers and highlights `pinnedSp.spId` via `selectedBusId`; line callbacks stay stubs.
  * A second `<DetailCard>` renders inside the right-pane fragment (after `pane-badge`). `.compare-pane` is `position: relative`, so it anchors to the right pane's top-left cleanly.

* Do NOT touch: `GridMap.tsx` (hover already fires `onBusHover(sp_id, props)` via the alias) or `ercot_state.py` (SPP surfacing already exists via `ercot_spp_range`).

## Acceptance

* [x] Hovering an SP dot on the ERCOT pane in `split` mode raises a DetailCard in that pane's top-left showing `sp_id`, `sp_type`, `load_zone` (or `—`), `Congestion` (signed `$/MWh`), and `DAM SPP` (`$/MWh`).
* [x] Hovering a bus on the model pane simultaneously with an SP on the ERCOT pane shows both cards — one per pane, no visual overlap.
* [x] Clicking an SP pins the ERCOT-side card; the `×` close button clears it. Independent of any pinned bus on the model side.
* [ ] `curl http://localhost:8000/topology | jq '.settlement_points.features[0].properties'` includes `load_zone` (may be `null`). *(needs cache rebuild + runtime check)*
* [ ] API startup log carries `SP load_zone tagged N/M via name prefix` from `_settlement_points_feature_collection`. *(needs runtime check)*
* [x] SPs with no congestion for the current interval show `Congestion: —` rather than `$0/MWh` or omitting the row. Same for `DAM SPP: —` when SPP is missing.
* [x] Single-mode and diff-mode paths are unchanged — the second DetailCard lives inside the right-pane fragment, which only renders in split mode.
