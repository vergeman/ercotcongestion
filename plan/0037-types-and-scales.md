# B1 - types-and-scales

Type: refactor
Branch: refactor/0037-types-and-scales

## Goal

* Rename `fragility` and rewrite the `ViewMode` union in `web/src/api/types.ts` to the four-view scheme (`modeled_congestion`, `lmp`, `congestion_vs_basis`, `binding_proximity`); add `binding_proximity` on `BusState` and the five new keys on `SnapshotMeta`.
* Rewrite `web/src/lib/colors.ts`: delete the fragility + fragility-z scales, add a diverging `modeledCongestionColor` (window-percentile anchors, symmetric around 0) and a sequential `bindingProximityColor` ([0, 1] with mild gamma), rename `computeRankDelta` → `computeCongestionVsBasisRank` (signed on both inputs).
* Update `web/src/index.css`: replace `--frag-*` CSS variables with `--mc-{neg,zero,pos}` and `--prox-{low,high}` matching the JS palette, and delete unreferenced vars.

## Context

* Depends on Sprint 2B B1 (`refactor/0034-api-schema-and-state`) for the renamed Pydantic types the frontend types must mirror.
* Parallelizable with 2A/2B — types + color code compile in isolation against local mocks; the map/legend/panel branches (0038-0040) consume this branch's exports.
* Recommendations from sprint2c-plan.md §5 are locked here: window-percentile anchors for `modeled_congestion`; signed rank on both sides for `congestion_vs_basis`; fixed `[0, 1]` anchors for `binding_proximity`.
* Fragility-z is dropped entirely — proximity is already bounded, z-scoring it adds no signal.

## Approach

* Work in: `web/src/api/types.ts`, `web/src/lib/colors.ts`, `web/src/index.css`
* `web/src/api/types.ts`:
  * `BusState`: `fragility: number | null` → `modeled_congestion: number | null`; add `binding_proximity: number | null`.
  * `SnapshotMeta`: rename `fragility_total`/`fragility_top10_share` → `modeled_congestion_total`, `modeled_congestion_top10_share`; add `modeled_congestion_abs_total`, `binding_proximity_max`, `binding_proximity_p95`.
  * `ViewMode`: `"modeled_congestion" | "lmp" | "congestion_vs_basis" | "binding_proximity"`.
  * `ScatterPoint`: rename `fragility` → `modeled_congestion`; add signed `basis` alongside `abs_basis` to match 2B B2 payload.
* `web/src/lib/colors.ts`:
  * Delete: `FRAGILITY_FLOOR`, `FRAGILITY_RED`, `FRAGILITY_GAMMA`, `FRAGILITY_RED_CORE`, `FRAGILITY_ANCHORS`, `fragilityColor`, `normalizeFragility`, and the entire fragility-z section (`BusZStats`, `computeBusZStats`, `fragilityZ`, `fragilityZColor`).
  * Add `MODELED_CONGESTION_ANCHORS` (window-percentile: `p_high = percentile(|mc|, 0.99)`, `p_low = -p_high`, floor near 0), `normalizeModeledCongestion(buses) -> Map<string, number>` returning signed values in ~[-1, 1], `modeledCongestionColor(norm)` returning diverging blue↔cream↔red (blue = export/negative, red = import/positive, cream = zero). Reuse LMP scale's RGB endpoints for palette consistency.
  * Add `BINDING_PROXIMITY_ANCHORS = { low: 0, high: 1.0, ticks: [0, 0.5, 0.9, 1.0] }`, `normalizeProximity(v)` (clamp + mild gamma so 0.9+ pops), `bindingProximityColor(norm)` (sequential, colorblind-safe green→yellow→red).
  * Rename `computeRankDelta` → `computeCongestionVsBasisRank`, taking signed `modeled_congestion` and signed `basis` (drop `abs()`). Keep the teal/purple `rankDeltaColor` palette unchanged.
  * Export all new anchor consts for `Legend.tsx` (0038).
* `web/src/index.css`:
  * Delete `--frag-0` through `--frag-max` (lines 21-25).
  * Add `--mc-neg`, `--mc-zero`, `--mc-pos`, `--prox-low`, `--prox-high` matching JS palette hexes.
  * `--frag-high` (used by ValidationPanel accent) — rename to `--mc-accent` for 0040 to pick up; ValidationPanel edits happen in 0040.
* Do NOT touch: `App.tsx`, `Header.tsx`, `GridMap.tsx`, `Legend.tsx`, `DetailCard.tsx`, `StatsPanel.tsx`, `ValidationPanel.tsx`, `TimelineSparkline.tsx`, `events.ts` — those are 0038-0041.

## Acceptance

* [ ] `web/src/api/types.ts` — `BusState`, `SnapshotMeta`, `ViewMode`, `ScatterPoint` updated per §3.1; no `fragility` identifiers remain in the file.
* [ ] `web/src/lib/colors.ts` — fragility + fragility-z symbols deleted; `modeledCongestionColor`, `bindingProximityColor`, `computeCongestionVsBasisRank` exported with anchor consts.
* [ ] `web/src/index.css` — `--frag-0..--frag-max` removed; `--mc-*` and `--prox-*` present; `--mc-accent` present for ValidationPanel handoff.
* [ ] `tsc --noEmit` inside `web/` errors only in files that import the deleted fragility symbols (expected until 0038-0041 land); no errors originate inside `types.ts` / `colors.ts`.
* [ ] `grep -n "fragility\|FRAGILITY\|frag-" web/src/api/types.ts web/src/lib/colors.ts web/src/index.css` returns 0 hits.
