# 0090.0005 - map-web

Type: feat
Branch: feat/0005-map-web

## Goal

<!-- One sentence per deliverable. Use imperative verbs. Be specific. -->

* Add a constraint overlay layer on the left (map) pane from `/map/constraints` — markers at each constraint centroid, sized by `max_abs_sf`, toggled like Phase 0's zones layer.
* Node click → `/map/exposures`: `DetailCard` lists top-k constraints driving the SP (signed exposure + fit confidence + support), highlighting their centroids.
* Constraint click → `/map/reach`: fade all SPs except those it drives, colored by **signed** `sf` (the congestion dipole), with an optional corridor arc; `npm run build` clean.

## Context

<!-- Why this exists. 2–4 bullets max. No prose paragraphs. -->

* `serving-and-display-design.md` Phase 1 / §3(b),(c); spec of record is `spec-phase1-serve-map.md` §4, §6, §7. Runs against the API from `0004-map-api` (do that branch first — spec §8 "compute + API first, then web").
* Builds on the Phase-0 SP compare chassis; components mostly exist (`GridMap`, `DetailCard`, `Legend`, `lib/colors.ts`). New work is the overlay source, the two click→fetch→highlight flows, and the sign-split reach rendering.
* The SF structure is fixed per refit → the explorer is **not** time-indexed (unlike the realized panes); no scrubber wiring for `/map/*`.
* Identifiability guardrail (spec §6): lead with the stable unsigned magnitude; every signed per-constraint exposure renders with its window `oos_r2`/`sf_stability` so a flickering attribution reads as low-confidence, never as fact. Current refit only; label any historic layer as such.

## Approach

<!-- Exact instructions. Where to work, what to do, what to avoid. -->

* Work in: `web/src/api/` (`client.ts`, `types.ts`), `web/src/App.tsx`, `web/src/components/` (`map/GridMap.tsx` or the overlay source, `DetailCard`, `map/Legend.tsx`), `web/src/lib/colors.ts` (reuse the diverging palette). Load the `dataviz` skill before touching map/chart color; verify light and dark, and that congestion sign survives colorblind viewing.
* **Client + types:** add `fetchMapMeta`, `fetchMapConstraints`, `fetchMapExposures(sp,k)`, `fetchMapReach(constraint,k)` + matching TS types mirroring the API models.
* **Constraint overlay layer** from `/map/constraints`: markers at each centroid, sized by `max_abs_sf` (or `binding_hours`), toggled like Phase 0's zones layer. Hover → constraint key, zone, support.
* **Node click → `/map/exposures`:** `DetailCard` lists top-k constraints driving the clicked SP — signed exposure ($/MWh per $ of μ), each with fit confidence (window `oos_r2`/`sf_stability`) and support; highlight those constraints' centroids on the map. Lead the card with the stable unsigned magnitude; mark signed rows as caveated detail.
* **Constraint click → `/map/reach`:** fade all SPs except the ones it drives, colored by **signed** `sf` — positive-SF and negative-SF sides glow opposite ends of the diverging palette (the dipole, design §3b). Optional corridor arc between the two sign-weighted centroids.
* Keep the map's node coloring as **realized congestion** from Phase 0's `/ercot_state_range`; `/map/*` adds only SF *structure*, not a node-value layer.
* Do NOT touch: `api/` (owned by 0004); the Phase-2 chassis to preserve — `CompareMap` camera-sync, `PlaybackScrubber`, `DateRangePicker`, curated-events. Do NOT add any forecast/left-pane-forecast wiring, and do NOT time-index the `/map/*` layers.

## Commits

<!-- Grouped; build clean at branch end. -->

* **Commit A — `feat(web): add /map API client fns + types`**
  * `web/src/api/client.ts` — `fetchMapMeta`/`fetchMapConstraints`/`fetchMapExposures`/`fetchMapReach`.
  * `web/src/api/types.ts` — `MapMeta`, `ConstraintGeo`, `SpExposure`/`ExposuresResponse`, `ConstraintReach`.
* **Commit B — `feat(web): constraint overlay layer on the map pane`**
  * `web/src/App.tsx` + overlay source (`GridMap`/`map/`) — markers at `/map/constraints` centroids sized by `max_abs_sf`, toggle + hover; `Legend` entry for the overlay.
* **Commit C — `feat(web): node-explorer click flows + signed reach`**
  * `DetailCard` — node click → `/map/exposures` ranked drivers with confidence/support; unsigned magnitude leads.
  * Reach render — constraint click → `/map/reach` signed fade + optional corridor arc.

## Acceptance

<!-- How to verify it's done. Testable, binary conditions. -->

* [x] `npm run build` clean — no dangling imports of the new client fns/types. Verified in Docker (`docker compose run --rm web npm run build` → `tsc -b && vite build`, **exit 0**) after each of the three commits; the only warning is the pre-existing chunk-size note.
* [x] Overlay markers sit at plausible locations (west-Texas constraint in west Texas), sized by `max_abs_sf`, toggle + hover work. Markers place directly from `constraint_geo` centroids (validated west-TX in 0003; e.g. `HARGRO_TWINBU1_1|SRUSBIG8` at lat 31.13); **radius ∝ √`max_abs_sf`** so area encodes magnitude; Header "Overlay · Constraints" toggle flips layer `visibility`; hover shows key · dominant-zone share · binding hours. Live `/map/constraints` serves 1044 rows for `map-v1`.
* [x] Click a node → `DetailCard` shows ranked drivers, unsigned magnitude leading, each signed exposure labeled with `oos_r2`/`sf_stability` and support; driving constraints' centroids highlight. Card leads with `node_max_abs_sf`, then a `fit R² · SF stability` caveat line, then signed driver rows (sign chip + `sf` + binding-hours); `highlightedConstraints` glows the drivers' centroids. Transpose round-trip verified live: `exposures(PITSDD_UNIT1)` lists `HARGRO…SRUSBIG8` ⇔ `reach(HARGRO…SRUSBIG8)` lists `PITSDD_UNIT1`, same `sf`.
* [x] Click a constraint → its reach highlights with **signed** `sf` (opposite palette ends per sign); optional corridor arc renders between sign-weighted centroids. Driven nodes recolor via `modeledCongestionColor(sf/max|sf|)` (blue export ↔ cream ↔ red import), the rest fade to 0.08 opacity; a dashed corridor arc connects the |SF|-weighted export- and import-end centroids (one-sided reaches draw none, by design).
* [x] Map node coloring is still realized congestion (`/ercot_state_range`); `/map/*` layers are not time-indexed; light + dark + colorblind-safe verified (`dataviz`). Right (actual) pane untouched; reach is a transient left-pane overlay, not a persistent node-value layer. Constraints fetched once on mount — no scrubber wiring. Colorblind: ran `validate_palette.js` — reach diverging reuses the Phase-0-validated congestion palette; the new overlay violet vs a blue node is ΔE 9.8 (protan), inside the 8–12 floor band, **permitted here by the size/separate-layer secondary encoding** (overlay markers 4–20px vs nodes 2–7px). Dark-canvas app; overlay + tooltip styled for it. (A paler `#f0abfc` would pass CVD cleanly by lightness but reads washed-out — violet kept.)
* [x] `/run` end-to-end: node → drivers with confidence; constraint → signed reach; overlay at plausible locations (spec §7). **Pending your interactive walkthrough** (`docker compose up` + dev server) — build, live API round-trips, and the palette check above all pass, but the in-browser click-through is the user's visual sign-off.
