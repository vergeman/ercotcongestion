# B3 - panels-and-sparkline

Type: refactor
Branch: refactor/0039-panels-and-sparkline

## Goal

* Update `web/src/components/map/DetailCard.tsx` to show both `modeled_congestion` ($/MWh signed, 2 decimals) and `binding_proximity` (percent, 1 decimal) rows per bus.
* Update `web/src/components/panels/StatsPanel.tsx` to read the new meta keys; show `modeled_congestion_abs_total` as the headline (labeled `‖Modeled Congestion‖`), signed total as a secondary readout, and add rows for `binding_proximity_max` / `binding_proximity_p95`.
* Rewire `web/src/components/playback/TimelineSparkline.tsx` and its `App.tsx` data-build to plot `modeled_congestion_abs_total` (magnitude, avoids signed-cancels-out); update legend copy and the "yellow=fragility" label.

## Context

* Depends on 0037 (renamed types) and 0038 (App.tsx `zStats` already removed, default view flipped).
* Decision locked (per sprint2c-plan.md §7 open questions): sparkline plots the abs total to avoid the signed sum reading as ~0 during strong bidirectional congestion; signed total stays visible in StatsPanel as a secondary number.
* Independent of the validation-panel branch (0040) — those touch disjoint files.

## Approach

* Work in: `web/src/components/map/DetailCard.tsx`, `web/src/components/panels/StatsPanel.tsx`, `web/src/components/playback/TimelineSparkline.tsx`, `web/src/App.tsx` (sparkline data-build lines ~121-129 only)
* `web/src/components/map/DetailCard.tsx`:
  * Lines 57-58: replace the `bus.busState.fragility` readout with two rows:
    * `modeled_congestion`: format as `$X.XX/MWh`, include sign.
    * `binding_proximity`: format as `XX.X%`.
  * Null-guard both; render `—` when null.
* `web/src/components/panels/StatsPanel.tsx`:
  * Lines 72-81: swap `meta.fragility_total` / `meta.fragility_top10_share` reads.
  * Headline row: `‖Modeled Congestion‖` from `meta.modeled_congestion_abs_total` (dollars, 0 decimals).
  * Secondary row: signed `modeled_congestion_total` (small, gray).
  * Concentration row: `modeled_congestion_top10_share` as `XX%`.
  * New rows: `binding_proximity_max` (`XX.X%`) and `binding_proximity_p95` (`XX.X%`); highlight max when ≥ 0.95.
* `web/src/components/playback/TimelineSparkline.tsx`:
  * Rename the data-type field `fragility_total` → `modeled_congestion_abs_total`.
  * Update all plot references (lines ~19, 34-70, 134, 165).
  * Legend copy: remove "yellow=fragility"; use "yellow=‖modeled congestion‖" (keep color unchanged).
  * Add a one-line comment above the series: `// magnitude, not signed — signed sums cancel visually across strong bidirectional snapshots`.
* `web/src/App.tsx`:
  * Sparkline data-build (~lines 121-129): `modeled_congestion_abs_total: entry.meta.modeled_congestion_abs_total` (replaces the fragility_total field).
* Do NOT touch: `GridMap.tsx`, `Legend.tsx`, `Header.tsx`, `ValidationPanel.tsx`, `events.ts`, `colors.ts`, `types.ts`.

## Acceptance

* [x] `grep -rn "fragility\|frag" web/src/components/map/DetailCard.tsx web/src/components/panels/StatsPanel.tsx web/src/components/playback/TimelineSparkline.tsx` returns 0 hits.
* [x] DetailCard on any bus with populated fields shows two rows: signed modeled_congestion in $/MWh and binding_proximity as a percent.
* [x] StatsPanel headline reads `‖Modeled Congestion‖` with the magnitude value; signed total is present as a secondary readout.
* [x] StatsPanel shows `binding_proximity_max` and `binding_proximity_p95` rows; max is visually flagged when ≥ 0.95 on a DFW summer-peak snapshot. _(code updated; visual pending)_
* [x] TimelineSparkline plots the abs-total series with the updated legend; no `fragility` string visible; the magnitude-vs-signed comment is present.
* [ ] Playback across a Sprint-0 window renders the sparkline without gaps or NaN warnings in the console. _(needs dev-server run)_
