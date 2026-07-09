# 0078 - statspanel-layout-and-lmp-legend

Type: refactor
Branch: refactor/0078-statspanel-layout-and-lmp-legend

## Goal

* Reorder `StatsPanel`: System State renders first.
* Split the scorecard headline (rank ρ, mean r, sign%, hours) into its own "Cluster Correlations" section, separate from the per-zone table.
* Remove the LMP Range section from `StatsPanel`; render current-snapshot LMP min/mean/max in each map's `Legend` (model pane and ERCOT pane) instead.

## Context

* `StatsPanel.tsx` currently orders: Cluster Scorecard (headline + zone rows together) → System State → LMP Range → Binding Constraints → Contingencies → Outages → Dispatch.
* The headline stats (`zone_rank_spearman_per_hour`, `mean_corr`, `mean_sign_agreement`, `n_hours`) already exist on `ScorecardResponse.headline` — no new API/compute data needed for the new section.
* `meta.lmp_min/lmp_mean/lmp_max` (`SnapshotMeta`) is read nowhere except `StatsPanel.tsx` today. The maps already carry a *window-wide* LMP range in `Legend.tsx` via the `lmpStats`/`rightLmpStats` props (percentile-based, independent of `meta`). Per-snapshot min/mean/max is not currently shown on the maps.
* `Legend.tsx` already receives the raw per-pane bus array (`buses` for model, `ercotBuses` for ERCOT — both `BusState[]` with `.lmp` populated) and already derives a per-snapshot histogram from it (`lmpHist`, lines 57-70). A per-snapshot min/mean/max can be derived the same way, in-component, with no new props.
* Both map panes already instantiate `Legend` independently (`App.tsx:633` for ERCOT/`palette-only`, `App.tsx:708` for model/`full`), so per-pane snapshot stats fall out naturally once computed from `buses`.

## Approach

* Work in: `web/src/components/panels/StatsPanel.tsx`, `web/src/components/map/Legend.tsx`
* Entry point: `StatsPanel` JSX body (section order/grouping); `Legend`'s `isLmp` render block.
* Step 1 — `StatsPanel.tsx`: move the "System State" `panel-section` block to render first, before any scorecard content.
* Step 2 — `StatsPanel.tsx`: split the existing `{scorecard && (...)}` block into two independent sections:
  * "Cluster Correlations" — the `scorecard-headline` grid only (rank ρ / mean r / sign% / hours tiles), still gated on `scorecard`.
  * "Cluster Scorecard" — the zones-toggle button + `scorecard-rows` table (header row + per-zone rows), unchanged in content and behavior.
* Step 3 — `StatsPanel.tsx`: delete the "LMP Range" `panel-section` block entirely (the one reading `meta.lmp_min/lmp_mean/lmp_max`), along with its now-unused `.lmp-range`/`.lmp-item` styles.
* Step 4 — `Legend.tsx`: inside the `isLmp` branch, add a `useMemo` that computes `{min, mean, max}` from `buses` (filter `b.lmp != null`), and render it as an additional `legend__sub` line under the existing window-stats line, for both `variant="full"` and `variant="palette-only"` (so it shows on model and ERCOT panes alike). Label it distinctly from the existing "window ... · P.." line (e.g. "snapshot $x – $y · avg $z") so the two ranges (window vs. current snapshot) aren't confused.
* Do NOT touch: `meta.lmp_min/lmp_mean/lmp_max` fields in `api/types.ts` or backend — leave the field defined, just stop consuming it in `StatsPanel`.
* Do NOT touch: `mcStats`/modeled-congestion legend blocks, binding-proximity legend blocks, zone swatches, or line-status key in `Legend.tsx`.
* Do NOT touch: scorecard sort/selection logic (`sortedZones`, `tightSet`, `onSelectCluster`) or any compute/API layer.

## Acceptance

* [x] "System State" is the first `panel-section` rendered in `StatsPanel`.
* [x] "Cluster Correlation" section renders the four headline tiles, independent of the per-zone table section.
* [x] "Cluster Scorecard" section still renders the zones toggle and unchanged per-zone rows/columns.
* [x] "LMP Range" section no longer renders in `StatsPanel`; `meta.lmp_min/mean/max` are unused in that file.
* [x] Both model and ERCOT `Legend` instances show a current-snapshot LMP min/mean/max line, computed from their respective `buses` prop, with no new props/API fields added.
* [x] `npm run build` (or `tsc --noEmit`) passes in `web/`.
* [x] Manual browser check: new section order, headline/scorecard split, and both legends' snapshot-range line render correctly.
