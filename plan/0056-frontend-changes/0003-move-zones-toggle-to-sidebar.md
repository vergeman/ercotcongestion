# 0058 - move-zones-toggle-to-sidebar

Type: refactor
Branch: refactor/0058-move-zones-toggle-to-sidebar

## Goal

* Move the Zones toggle button out of the map Legend and into the StatsPanel sidebar, above the Cluster Scorecard section.
* The toggle stays a single source of truth (still lifts `showZones` state in App); only its render location changes.
* Keep the per-cluster color swatches — they are a legend, not a control — either in Legend (preferred) or move alongside the button. This plan keeps them in Legend so the palette + swatches stay adjacent.

## Context

* `Legend.tsx:239-264` renders the `Zones` toggle button plus (when active) a row of Z-id swatches. The button is a control; the swatches are a color key. Bundling them into the palette legend has crowded the map's bottom-left corner and made it harder to see the button when the palette pill is long.
* The Zones toggle is conceptually a sidebar/panel action — it changes what the whole map is coloring by, in the same way the Scorecard row selection does. `StatsPanel.tsx` already owns the cluster-scorecard interaction (`onSelectCluster`), and enabling Zones auto-fires there today (`App.tsx:85-91`).
* State (`showZones`) is already lifted to App (`App.tsx:72`) and threaded to both `Legend` and `GridMap`. This refactor doesn't change state ownership, just the button's render tree.
* This plan lands **before** plan 0059 (ERCOT-pane legend) so that when 0059 splits Legend into `full` / `palette-only` variants, the Zones controls are already gone from Legend — no duplicated cut/paste work, and the two plans stay consistent on what Legend still owns.

## Approach

* Work in: `web/src/components/panels/StatsPanel.tsx`, `web/src/components/map/Legend.tsx`, `web/src/App.tsx`.
* Entry point / primary change: cut the `<button className="legend__zones-toggle">` block from Legend and paste an equivalent into StatsPanel's header area; drop the corresponding props on Legend.

* **Step 1 — extend StatsPanel** (`StatsPanel.tsx`):
  * Add `showZones: boolean` and `onToggleZones: () => void` to the `Props` interface.
  * Render the toggle above the `Cluster Scorecard` section header. Reuse Barlow Condensed / uppercase styling so it reads as a sidebar control, not a repurposed legend button. Suggested markup:
    ```
    <div className="panel-section panel-section--controls">
      <button
        type="button"
        className={"zones-toggle label" + (showZones ? " active" : "")}
        onClick={onToggleZones}
      >
        {showZones ? "Zones ✓" : "Zones"}
      </button>
    </div>
    ```
  * Style block: mirror the existing `.legend__zones-toggle` rules (border, hover accent, active accent) under the new `.zones-toggle` class so the visual affordance stays identical.

* **Step 2 — strip Legend** (`Legend.tsx`):
  * Delete the `<div className="legend__zones">` block (the toggle button). Keep the swatch list — render it in its own `<div className="legend__zones-swatches">` block gated on `showZones && tightClusterIds.size > 0`, still bordered above by the existing top divider.
  * Drop the `onToggleZones` prop entirely; keep `showZones` (still needed to gate the swatch row) and `tightClusterIds`.
  * Remove the `.legend__zones` + `.legend__zones-toggle` CSS rules; keep `.legend__zones-swatches` + `.legend__zone-swatch` + `.legend__zone-dot`.

* **Step 3 — rewire App** (`App.tsx`):
  * Drop `onToggleZones` from the `<Legend ... />` prop list (`App.tsx:554-563`).
  * Pass `showZones={showZones}` and `onToggleZones={() => setShowZones(s => !s)}` to `<StatsPanel ... />` (`App.tsx:583-588`).
  * Leave the auto-enable-on-select logic (`handleSelectCluster`, `App.tsx:85-91`) untouched — it still writes `setShowZones(true)` and the new button reflects that state.

* Do NOT touch: the Zones layer painting effects in `GridMap.tsx` (they read `showZones` prop, no change), the centroid label visibility effect (same), the diff-mode override (`comparisonMode === "diff" ? false : showZones` at `App.tsx:504` still stands).

* Watch out for: the button in the sidebar should not steal focus from scorecard row clicks. If the sidebar layout puts it flush against the first `.zone-row`, add a bottom border on the controls section to keep the visual hierarchy that "controls at top, list below."

## Acceptance

* [ ] The Zones toggle button no longer appears anywhere inside the map's Legend widget. Clicking around the bottom-left corner of the map does not toggle Zones.
* [ ] A Zones toggle button appears in the StatsPanel sidebar, above the Cluster Scorecard header, and toggles the exact same state — enabling it turns on cluster coloring across the model pane; disabling it restores congestion coloring.
* [ ] Selecting a scorecard row still auto-enables Zones (via existing `handleSelectCluster`); the sidebar button's active state reflects that immediately.
* [ ] The per-cluster color swatches (`Z1 Z2 …`) still render inside the map Legend when Zones is on, matching today's palette exactly.
* [ ] `Legend` no longer accepts `onToggleZones` as a prop. TypeScript build passes with no unused-import or missing-prop warnings.
* [ ] Diff mode behavior unchanged — button reads whatever state App holds, but the map override at `App.tsx:504` keeps ignoring `showZones` while in diff.
