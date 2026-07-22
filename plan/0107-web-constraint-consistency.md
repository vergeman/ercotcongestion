# 0107 - web-constraint-consistency

Type: fix
Branch: fix/0107-web-constraint-consistency

## Goal

* Web polish pass on the constraint view, side panel, and header nav.

## Tasks

* [x] Consistent +/- export/import blue/red constraint view
* [x] Stats Panel label fixes
* [x] SidePanel: increase row-label font size (`.np-stat .label`, `.sc-cat` → 12.5px)
* [x] SidePanel: increase scorecard table header size (`.sc-h` → 12px)
* [x] SidePanel: "View full scoreboard" link opens in new tab
* [x] HeaderNav: Scoreboard link opens in new tab (per-entry `newTab` flag)
* [x] DateRangePicker: add close (✕) button; raise dropdown max-height 70vh→90vh so Load button fits without scroll
* [x] Legend: anchor end ticks (lo/hi) to bar edges so they no longer bleed outside the container
* [x] Legend: drop misleading `(−)`/`(+)` from congestion labels → plain `Export` / `Import` (ticks already carry sign)
* [x] ConstraintPanel: plain-language hover tooltips on Predicted / Realized toggle
* [x] ConstraintPanel: brighten dark-theme text (caption, meta line) `--text-muted`→`--text-secondary`

## Files

* `web/src/components/panels/SidePanel.tsx`
* `web/src/components/layout/HeaderNav.tsx`
* `web/src/components/playback/DateRangePicker.tsx`
* `web/src/components/map/Legend.tsx`
* `web/src/components/panels/ConstraintPanel.tsx`
