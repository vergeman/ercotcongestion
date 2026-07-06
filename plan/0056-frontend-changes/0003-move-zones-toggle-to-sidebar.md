# 0058 - move-zones-toggle-to-sidebar

Type: refactor
Branch: refactor/0058-move-zones-toggle-to-sidebar

## Goal

Move the Zones toggle out of the map Legend into the StatsPanel Cluster Scorecard section. Keep the per-cluster swatches in Legend (they're a color key, not a control). `showZones` stays lifted in App — only the button's render location changes.

## Context

* `Legend.tsx` bundles a control (the toggle) with a color key (swatches), crowding the map's bottom-left corner.
* The toggle is conceptually a sidebar action — it changes what the map colors by, like scorecard row selection does (`handleSelectCluster` already auto-fires `setShowZones(true)`).
* Lands before plan 0059 (ERCOT-pane legend split) so the Zones controls are gone from Legend before it's variantized.

## Approach

Files: `web/src/components/panels/StatsPanel.tsx`, `web/src/components/map/Legend.tsx`, `web/src/App.tsx`, `web/src/components/map/GridMap.tsx`.

* **Step 1 — StatsPanel**: add `showZones` + `onToggleZones` props. Render a `.zones-toggle` button inside the Cluster Scorecard `panel-section`, between the headline stats and the rows head row. Mirror the existing `.legend__zones-toggle` styling.

* **Step 2 — Legend**: drop `onToggleZones` prop and the `<div className="legend__zones">` toggle block. Keep the swatch row (gated on `showZones && tightClusterIds.size > 0`); move the top-divider styling onto `.legend__zones-swatches`. Delete the `.legend__zones` + `.legend__zones-toggle` CSS.

* **Step 3 — App**: drop `onToggleZones` from `<Legend />`; pass `showZones` + `onToggleZones={() => setShowZones(s => !s)}` to `<StatsPanel />`. Leave `handleSelectCluster`'s auto-enable and the diff-mode override untouched.

* **Step 4 — GridMap (bugfix)**: the congestion/LMP repaint effect early-returns on `!buses.length`, so toggling Zones off with no snapshot loaded leaves cluster colors stuck. Fix: when `buses` is empty but `topology` is present, walk topology and `map.removeFeatureState({source:"buses", id}, "color")` to drop the cluster color and fall back to default paint. Add `topology` to the effect deps.

Do NOT touch: `GridMap`'s Zones paint effect, the centroid-label effect, or the diff-mode override at `App.tsx:504`.

## Acceptance

* [ ] Zones toggle no longer appears in the map Legend.
* [ ] Zones toggle appears in StatsPanel, inside the Cluster Scorecard section (between headline stats and rows head), and toggles the same state.
* [ ] Scorecard row selection still auto-enables Zones; sidebar button reflects state immediately.
* [ ] Per-cluster swatches (`Z1 Z2 …`) still render in the Legend when Zones is on.
* [ ] Toggling Zones off clears bus coloring even when no snapshot window is loaded (buses return to default color).
* [ ] `Legend` no longer accepts `onToggleZones`. `tsc --noEmit` passes clean.
* [ ] Diff-mode behavior unchanged.
