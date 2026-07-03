# 0048 - frontend-comparison-view

Type: feat
Branch: feat/0048-frontend-comparison-view

## Goal

* Fold the S2 zone scorecard into the Stats panel; retire the Validation tab.
* Render tight ERCOT clusters as point-tag halos on the model map, driven by scorecard interaction.
* Add a Split / Single / Diff mode switch so model and ERCOT congestion can be compared side by side.
* Wire the data layer (ERCOT SP snapshots, zone geometry, per-hour Z-series) into the prefetch window.

## Context

* S1 (zone data) and S2 (`/validation` scorecard endpoint returning `zones` + `series.model_Z`/`ercot_Z`) are landed.
* Frontend today: single `GridMap`, view pills in `Header` drive `ViewMode` in `App.tsx`, right panel has Stats/Validation tabs (`ValidationPanel.tsx` is a stub since 0047).
* Backend today: `/topology` returns `{buses, lines, zones: null}` — zones payload is unshipped; no ERCOT SP source; no per-hour Z endpoint separate from `/validation`.
* Zones are anchor clusters (5–7 tight, rest gray) — display membership via feature-state halos, not 12 border colors.
* Each `## S3.x` section below is its own commit (or small commit set). **Pause after each section for review** before moving on. Final commit is user's.

## Approach

### S3.1 — Retire Validation tab, fold scorecard into Stats

* Work in: `web/src/App.tsx`, `web/src/components/panels/StatsPanel.tsx`.
* Remove `panelTab` state, `.panel-tabs` markup + CSS, and the `ValidationPanel` import; delete `components/panels/ValidationPanel.tsx`.
* Add a `useScorecard(runId)` fetch (via existing `fetchScorecard` in `api/client.ts`) — run_id sourced from a new prop on `App` (hard-code the current run for now; picker is out of scope).
* In `StatsPanel`, add a **Cluster Scorecard** section beneath System State: one row per `ScorecardZone` with `{cluster_id, n_buses, corr, sign_agreement, model_side_std}`; headline row shows `rank_spearman`, `mean_corr`.
* Row click sets a lifted `selectedClusterId` state in `App` (passed down as prop) — consumed by S3.2 for map highlighting. No map wiring yet, just state.
* Do NOT touch: `GridMap.tsx`, colors, or view modes in this section.
* **Acceptance**
  * [ ] Validation tab and its CSS are gone; `StatsPanel` renders the scorecard list under existing sections.
  * [ ] Clicking a scorecard row updates `selectedClusterId` (verify via React DevTools or a temp console log).
  * [ ] `ValidationPanel.tsx` file is removed; no dead imports.

### S3.2 — Cluster point-tag rendering

* Work in: `web/src/components/map/GridMap.tsx`, `Legend.tsx`, `lib/colors.ts`; extend `api/types.ts` if a zones payload lands.
* Add a `bus.cluster_id` join: the scorecard already ships `zones[].outlier_buses` — but we need per-bus membership. Load it either (a) from `/topology` if the backend now ships `zones`, or (b) derive from the scorecard payload by requesting a `members` field. **Prefer (a)** — add `cluster_id` to bus properties in `topology_builder.py` reading `runs/<run_id>/clustering/*.csv` (single-line addition to `_buses_feature_collection`).
* Palette: 5–7 named clusters get distinct hues from `lib/colors.ts` (new `clusterColor(id)`); everything else is `--bg-muted` gray.
* Selection interaction: `selectedClusterId` prop drives `feature-state`: members get `halo_opacity=0.8`, non-members dim to `circle-opacity: 0.2`. Reuse the existing halo layer plumbing pattern from PTDF halos.
* Centroid labels: add a `symbol` layer on a synthetic point source (centroid per cluster), toggled by a new "Zones" layer button in `Legend`.
* **No polygons** — leave `zones: null` display path alone; hulls are out of scope.
* Do NOT touch: PTDF halo code paths (S3.2 halos use different feature-state keys — `cluster_halo_*`).
* **Acceptance**
  * [ ] Named clusters render in their assigned colors; hovering a scorecard row halos its members and dims the rest.
  * [ ] Zones layer toggle in Legend shows/hides centroid labels.
  * [ ] PTDF hover halos still work unchanged.

### S3.3 — Three-mode comparison

* Work in: `web/src/App.tsx` (new `comparisonMode` state), `Header.tsx` (replace view pills with a mode switch), `GridMap.tsx` (accept a `side: 'model' | 'ercot'` prop), new `components/map/CompareMap.tsx` shell that renders two synced `GridMap`s.
* State: `type ComparisonMode = 'split' | 'single' | 'diff'`; default `'split'`. Keep existing `ViewMode` (color palette) as a sub-control shown in Single mode only.
* Split: two `GridMap` instances share camera via `map.on('move', ...)` mirroring (not `syncMaps` — avoids extra dep). Shared scrubber index is already lifted in `App`. Left = model buses, right = ERCOT SPs (new source added in S3.4).
* Single: current single-pane behavior; toggle between model and ERCOT via a secondary control.
* Diff: single-pane choropleth. Fill each cluster polygon (or bus-halo group if polygons unavailable) by `model_Z(t) − ercot_Z(t)` from `scorecard.series` at the current hour. Diverging palette in `lib/colors.ts` (new `zoneDiffColor(delta)`).
* Do NOT touch: PTDF halos, existing bus-hover/click paths inside `GridMap` — pass the side identity down so callbacks can namespace pinned state per-side (or lift pinned state per-side into `App`).
* **Acceptance**
  * [ ] Mode switch replaces the four view pills; palette selector visible only in Single.
  * [ ] Split view: two panes synced on pan/zoom + scrubber; distinct fills per side.
  * [ ] Diff view: per-cluster color equals `model_Z − ercot_Z` at scrubber hour; legend renders diverging scale.

### S3.4 — Data plumbing

* Work in: `web/src/api/client.ts`, `prefetch.ts`, `types.ts`; backend `api/topology.py` + `services/topology_builder.py` for zone geometry; new `api/ercot_state.py` router for ERCOT SP snapshots.
* Backend: add `/ercot_state_range?start=&end=` returning `{entries: [{interval_ts, sps: [{sp_id, congestion}]}]}`. Read from the same run directory the model uses; if the ERCOT parquet is missing return `503` (no synthesis).
* Backend: emit `zones: FeatureCollection` in `/topology` payload when `runs/<run_id>/clustering/polygons.geojson` exists; leave `null` when it doesn't.
* Frontend: extend `prefetchWindow` to fan out `state_range` and `ercot_state_range` in parallel; add caches keyed the same way. Extend `StateRangeEntry` with an optional `ercot_side` block on the type.
* `series.model_Z` / `series.ercot_Z` are already served by `/validation` — no new endpoint needed for Diff mode; scorecard fetch is enough.
* Do NOT touch: `/state`, `/state_range`, `/validation`, `/ptdf` — additive only.
* **Acceptance**
  * [ ] `curl /ercot_state_range?...` returns a non-empty payload for a known window; missing-data window returns 503.
  * [ ] `/topology` includes `zones` as a FeatureCollection when the polygons file exists.
  * [ ] `prefetchWindow` populates both model and ERCOT caches; existing playback works unchanged.

## Acceptance (overall)

* [ ] Split view renders model | ERCOT synced on the scrubber.
* [ ] Diff view choropleths cluster agreement per hour.
* [ ] StatsPanel shows the cluster scorecard; Validation tab gone.
* [ ] Zone membership legible via hover halo / dim, not 12 border colors.
* [ ] No regressions in PTDF halos, binding-line highlights, or contingency dashing.
