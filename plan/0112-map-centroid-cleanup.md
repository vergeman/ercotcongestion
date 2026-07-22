# 0112 - map-centroid-cleanup

Type: refactor
Branch: refactor/0112-map-centroid-cleanup

## Goal

* Strip the constraint centroid (`lat`/`lon`) and medoid (`core_lat`/`core_lon`) coordinates from every `/map/*` response — nothing renders them.
* Make the overview marks (metaball / corridor / radial ring) their own hit targets; delete the invisible `.ov-hit` circle.
* Anchor the radial ring at its peak-|SF| node instead of the medoid.
* Drop the four coordinate columns from `constraint_geo`; keep the metadata (zone/kV/spread/rail) columns.

## Context

* Only `/map/overview` `core_lat`/`core_lon` was still consumed — as the visible radial ring plus an invisible point hit-target for gtc/transmission. Every flat `lat`/`lon` centroid is unused on every endpoint.
* `constraint_geography` / `geo_panel` also feed the **μ-model** (`compute/mu/features.py:548` → `geo_lat`/`geo_zone_*`/`geo_dist_*` features). That path is out of scope — do not touch it. `constraint_core` (Weiszfeld medoid) is map-only.
* `/map/constraints/ranked` drives the panel's predicted/realized reorder — kept, only its coords stripped. The plain `/map/constraints` has no `/web` caller and is deleted wholesale from web + api; its `constraint_geo` metadata columns (`zone_shares`/`kv`/`spread_km`) stay in the DB (kept written by `geo_persist`), just unserved.

## Approach

* Work in: `web/src/`, `api/`, `compute/`, `db/migrations/`.

Per-endpoint field changes (`api/models.py` + the `SELECT` in `api/map.py` + the mirror types in `web/src/api/types.ts`):

* **`/map/overview`** (`OverviewConstraint`): drop `lat`, `lon`, `core_lat`, `core_lon`. Keep `ctype`, `binding_hours`, `max_abs_sf`, `nodes[]`.
* **`/map/reach`** (`ConstraintReach`): drop constraint-level `lat`, `lon`. Keep `max_abs_sf`, `n_rail`, `peak_offrail`, `binding_hours` (DetailCard verdict) and the per-node `sps[]` coords.
* **`/map/exposures`** (`SpExposure`): drop `lat`, `lon`. Keep `max_abs_sf`, `binding_hours`. Remove `g.lat`/`g.lon` from the join select.
* **`/map/constraints/ranked`** (`RankedConstraint` + `ConstraintLobe`): drop `core_lat`, `core_lon` and lobe `lat`/`lon`/`peak_sf`; `_lobe` returns `n_nodes` only. Keep `ctype`, `n_members`, `source_lobe.n_nodes`/`sink_lobe.n_nodes`.
* **`/map/constraints`** (`ConstraintGeo`): delete the endpoint, the `ConstraintGeo` model, the `ConstraintGeo` web type, and `fetchMapConstraints` (no caller). Its DB metadata columns stay written.

Then:

* **Web — `components/map/OverviewOverlay.tsx`** (SUPERSEDED — see Follow-on below): the SVG-mark-as-hit-target approach fought maplibre's own event system (clicks on nodes under a metaball/corridor didn't register). The SVG overlay was deleted entirely and re-implemented as native maplibre layers.
* **API tests**: update `api/tests/test_map.py` for the trimmed selects/models.
* **Compute — `compute/sf/geo_persist.py`**: stop writing `lat`, `lon`, `core_lat`, `core_lon`; drop the `constraint_core` call and the `_GEO_COLS` `geo_lat`/`geo_lon` copy. Keep the `spread_km`/`kv`/`zone_shares`/`max_abs_sf`/`n_rail`/`peak_offrail`/`binding_hours`/`ctype` writes.
* **Compute — `compute/mu/geo.py`**: delete `constraint_core` + `_weiszfeld` and their tests in `compute/mu/tests/test_geo.py`. Keep `constraint_geography`, `geo_panel`, `constraint_type`.
* **DB — `db/migrations/34_constraint_geo_drop_coords.sql`**: `ALTER TABLE constraint_geo DROP COLUMN` for `lat, lon, core_lat, core_lon` only.
* Do NOT touch: `constraint_geography`/`geo_panel`, `compute/mu/features.py`, the μ-model `geo_*` features, the `zone_shares`/`kv`/`spread_km` columns, or `nodes[].lat/lon` (SP coords).

## Follow-on: native maplibre overview rewrite + interaction + styling

The SVG `OverviewOverlay` was deleted; the de-piled overview is now drawn as native
maplibre layers, which fixed the node-click inconsistency (nodes are the base `sps`
layer, so their events are uniform).

* **New files** `web/src/components/map/overviewSources.ts` (GeoJSON builders + `sp_id → members` map; `mstEdges`/haversine moved here) and `OverviewPopover.tsx` (the multi-constraint box as a positioned `<div>`, no SVG).
* **Marks** (in `GridMap`, beneath `sps`): `ov-gtc` (blurred circle cloud) + `ov-gtc-glow` (halo), `ov-corridor` (MST lines, colored by `ctype` — GTCs emit their skeleton too, **unclipped**; transmission clipped at 150 km), `ov-radial` (ring at peak node). Isolation is a layer filter on `constraint_key`; the no-isolation state uses an explicit `["all"]` filter (not a null-clear).
* **Node → DetailCard flow**: node hover/click rides the base `sps` layer (`onSpHover`/`onSpClick`). A 2+ constraint node opens the popover; row hover previews that constraint (card + isolate), row click commits + **closes the box**.
* **Focus model (App)**: `effectiveConstraintId = hoveredConstraintId ?? lockedConstraintId`. Hover = transient overlay, click = lock (persists until another click / background / node click); hover never clears the lock. Node recolor uses `focusReach ?? reach` so the glow tracks the same effective constraint the marks isolate.
* **Styling**: `--sf-gtc` = gold `#e0a83a` (dark) / orange `#ea580c` (light), off the muddy mustard. Forecast-error diverging palette brightened, then set to **reuse the congestion blue↔red ramp** via `ERROR_USE_CONGESTION` in `lib/colors.ts` (blue = under, red = over). **Provisional — revisit with fresher eyes; flip the flag to `false` to restore emerald↔magenta.**

## Acceptance

Coordinate cleanup (committed):

* [x] No `/map/*` response carries `lat`/`lon`/`core_lat`/`core_lon`/`peak_sf`; `/map/constraints` returns 404; `/map/constraints/ranked` still responds, coords removed.
* [x] `geo_persist` writes the trimmed `constraint_geo` (coords absent, metadata intact); `constraint_core`/`_weiszfeld` deleted; μ-model `geo_*` features unchanged.
* [x] Migration 34 drops `lat, lon, core_lat, core_lon`; `api`/`compute` test suites pass.

Native overview + interaction (committed):

* [x] SVG `OverviewOverlay` deleted; overview drawn as native maplibre layers beneath `sps`.
* [x] Every node is clickable (incl. under a GTC cloud / on a corridor) → DetailCard; multi-constraint node opens the popover box.
* [x] Hover = transient, click = lock, un-hover reverts to the lock; the marks and the node glow follow the same effective constraint.
* [x] GTC MST skeletons render (incl. wide BASE-CASE interfaces like WESTEX); GTC cloud reads as a glowing region.

Provisional (revisit):

* [ ] Forecast-error palette: `ERROR_USE_CONGESTION = true` (congestion blue↔red) kept for now — confirm the SF glow still reads against it in the error view, or flip back to emerald↔magenta.
