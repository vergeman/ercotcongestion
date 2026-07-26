# 0119 - matrix-boundary-and-anchor-fixes

Type: fix
Branch: `fix/0119-matrix-boundary-and-anchor-fixes`

## Goal

* Resolve Matrix artifacts by their UTC delivery date.
* Make the Hubs / load zones preset include `HB_*` and `LZ_*` columns.
* Make settlement-point CSV metadata the canonical source for load zones in
  Matrix and map responses.
* Distinguish hub and load-zone aggregate price points on the map without
  obscuring the congestion/LMP color encoding.

## Context

* Forecast artifacts are stored by UTC date; Matrix currently selects them by Central date, losing five hours at the date boundary.
* The 2026-07-15 artifact has 15 hub/zone columns, including `HB_WEST` (max |SF| 0.734).
* Hub/zone centroid identifiers are maintained in `hubs_lz_centroids.csv` and
  appended to the geocoded settlement-point CSV by its generator.
* `load_zone` is currently inferred separately from settlement-point prefixes
  and is absent from map reach/overview responses.
* Hub/load-zone centroids can overlap aggregate or nearby nodal markers, making
  their separate map interactions difficult to see and select.

## Approach

* Work in: Matrix and map API routes/models, the settlement-point geocoder, and
  `web/src/components/map/GridMap.tsx`.
* Use the normalized UTC timestamp's calendar date for `load_daily_artifact`; retain the Central delivery-day label only if it remains a response/UI concern.
* Assign every geocoded settlement point to an ERCOT load-zone polygon using
  `assign_zone` and `LOAD_ZONES_GEOJSON`, then append normalized hub/load-zone
  centroid rows to the generated settlement-point CSV.
* Read `settlement_point_type` and `load_zone` from that CSV in Matrix,
  topology, and map reach/overview metadata; remove prefix-derived metadata.
* Rebuild the topology cache when its settlement-point CSV source changes.
* Render hubs as enlarged circular aggregate markers and load zones as diamond
  markers. Preserve the congestion/LMP fill, use neutral keylines plus `H`/`Z`
  labels for identity, and keep hover/selection treatment separate.
* Fan out coincident aggregate markers in screen space and adjust the manual
  centroid positions where needed to avoid visual collisions with nearby nodes.
* Make aggregate-marker fade and click behavior follow the same feature-state
  rules as ordinary nodes during constraint interaction.
* Keep the existing bounded, deterministic anchor ordering and column limits.
* Do NOT change artifact generation, database schema, map jobs, or pin behavior.

## Acceptance

* [x] A UTC artifact serves all 24 of its timestamps, including the five hours crossing a Central-date boundary.
* [x] `column_set=anchors` returns CSV-backed `HB_*` and `LZ_*` columns without pins.
* [x] The generated settlement-point CSV contains polygon-derived `load_zone`
  values for every geocoded point and normalized centroid rows at the top.
* [x] Matrix, topology, map reach, and map overview return CSV-backed
  settlement-point type and load-zone metadata.
* [x] Hubs and load zones are visually distinct, selectable, and fade with the
  normal node layer during constraint hover in both themes.
* [x] Existing core-column ordering remains unchanged.
* [x] Matrix and map API tests cover the metadata behavior; the frontend build
  type-checks the map contract.
