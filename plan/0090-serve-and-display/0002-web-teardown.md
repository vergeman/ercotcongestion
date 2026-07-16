# 0090.0002 - web-teardown

Type: refactor
Branch: refactor/0002-web-teardown

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Trim the web API client + types to the ERCOT settlement-point surface (drop model/scorecard/PTDF/IBP fns and types).
* Collapse `App.tsx` to the ERCOT-only compare view: left = `/ercot_state_range` (realized congestion), right = `/ercot_spp_range` (SPP), both rendering SPs.
* Retire the model-bus- and scorecard-specific components + prefetch fan-out, leaving `npm run build` clean and the app running on realized data.

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* `spec-phase0-teardown.md` §5; runs against the API already repointed by `0001-api-teardown` (do that branch first — spec §7).
* Decision (A) (spec §1): keep the two-map chassis + camera-sync/compare code that Phase 2 needs back; both panes just become ERCOT SP layers on realized data. No single-map collapse.
* This is the largest chunk of Phase 0 and the part most worth a careful diff; the API side was mechanical by comparison (spec §5.2–§5.3).
* The `spTopology` (SP-as-bus alias) path already exists in `App.tsx`; repointing rides on it. `ViewMode` collapses to ERCOT palettes only (`congestion`/`lmp`).

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `web/src/api/` (`client.ts`, `types.ts`, `prefetch.ts`), `web/src/App.tsx`, `web/src/components/` (`panels/StatsPanel.tsx`, `map/CompareMap.tsx`, `map/Legend.tsx`).
* `web/src/api/client.ts`: delete `fetchState`, `fetchStateRange`, `fetchScorecard`, `fetchPtdf`, `fetchIbpErcotRange`; keep `fetchTopology` (consumer shape changes), `fetchErcotStateRange`, `fetchErcotSppRange`.
* `web/src/api/types.ts`: delete `BusState`(model-side), `SnapshotMeta`, `State*`, `Scorecard*`, `MappingCorrelationSummary`, `Ptdf*`, `IbpErcot*`, `BusFeatureProperties`, `LineFeatureProperties`; keep the Ercot*/SP types; repoint `SPFeatureProperties` to drop `cluster_id`/`best_corr` and add `capacity_mw`.
* `web/src/App.tsx`: remove the synthetic model pane (`topology` buses branch, `buses`/`meta` state, `fetchState*`, `SnapshotMeta`, bus hover/click/pin, sparkline meta series) and scorecard/zones (`scorecard`, `selectedClusterId`, `showZones`, `tightClusterIds`, `handleSelectCluster`, `StatsPanel` scorecard wiring). Point left = `/ercot_state_range`, right = `/ercot_spp_range`, both on the existing `spTopology` path. Collapse `ViewMode` to `congestion`/`lmp`; drop `modeled_congestion` as a model-side mode.
* `web/src/components/`: retire the `StatsPanel` scorecard section, zones legend, PTDF overlays, and `CompareMap`'s model-side assumptions. Keep `GridMap`, `Legend`, `DetailCard`, `CompareMap`, `PlaybackScrubber`, `TimelineSparkline`, `DateRangePicker`, `lib/colors.ts`, prefetch/cache.
* `web/src/api/prefetch.ts`: drop the `getCached`/model-state fan-out; keep the ERCOT congestion/SPP caches.
* Do NOT touch: `api/` (repointed in `0001`); the chassis to preserve for Phase 2 — `CompareMap` camera-sync, `PlaybackScrubber`, `DateRangePicker`, curated-events, `lib/colors.ts`. Do NOT add any forecast/left-pane-forecast wiring (Phase 2).

## Commits

<!-- Grouped; build clean at branch end. -->

* **Commit A — `refactor(web): trim API client + types to ERCOT SP surface`**
  * `web/src/api/client.ts` — delete `fetchState`/`fetchStateRange`/`fetchScorecard`/`fetchPtdf`/`fetchIbpErcotRange`; keep the three ERCOT/topology fns.
  * `web/src/api/types.ts` — delete the model/scorecard/PTDF/IBP/bus/line types; repoint `SPFeatureProperties` (drop `cluster_id`/`best_corr`, add `capacity_mw`).
* **Commit B — `refactor(web): collapse App shell to ERCOT compare view`**
  * `web/src/App.tsx` — remove the model pane + scorecard/zones state and wiring; repoint left=`/ercot_state_range`, right=`/ercot_spp_range` on `spTopology`; collapse `ViewMode` to `congestion`/`lmp`.
* **Commit C — `chore(web): retire model/scorecard components + prefetch fan-out`**
  * `web/src/components/panels/StatsPanel.tsx` — remove the scorecard section.
  * `web/src/components/map/CompareMap.tsx`, `web/src/components/map/Legend.tsx` — drop model-side assumptions, zones legend, PTDF overlays.
  * `web/src/api/prefetch.ts` — drop the model-state fan-out; keep ERCOT congestion/SPP caches.

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [x] `npm run build` is clean — no dangling imports of deleted client fns or types. (`docker compose run --rm web npm run build`: `tsc -b` green, vite built; only the pre-existing chunk-size warning.)
* [x] The app loads a single ERCOT SP map with a working scrubber and no synthetic pane. (Vite serves `GET /` 200; `App.tsx` + all edited modules transform with no esbuild errors; HMR clean.)
* [x] Both panes render realized ERCOT settlement points and compare the **same** quantity under the active palette — left = prediction placeholder (identical actual values until Phase 2 swaps the source), right = actual ERCOT (`/ercot_state_range` congestion or `/ercot_spp_range` SPP per palette). Supersedes the original fixed left=congestion/right=SPP framing per the prediction-vs-actual clarification.
* [x] `ViewMode` exposes only `congestion`/`lmp`; no `modeled_congestion`, `binding_proximity`, scorecard, zones, or PTDF UI remains. `StatsPanel` deleted (was 100% meta/scorecard-driven).
* [x] `/run` end-to-end: `/topology` (1,092 SPs) and `/ercot_spp_range` (966–973 SPs/hr, live SPP) return realized data; the congestion pane renders wherever the served run has coverage. The congestion source (`/ercot_state_range`) is still the legacy run (`v1-annual-2`) — **acceptable for now, re-sourced in a future sprint** (spec §4).
