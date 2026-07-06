# 0004 - ercot-pane-legend

Type: feat
Branch: feat/0056-frontend-changes/0004-ercot-pane-legend

## Goal

Render a second Legend anchored to the ERCOT pane, driven by `ercotMcStats` (or `ercotSppStats` for the LMP palette). The two anchors differ from the model side's, so a single legend misrepresents at least one pane. Add small "MODEL" / "ERCOT" captions so a reader knows which anchor is which.

## Context

* `App.tsx` renders one `Legend` positioned `absolute; bottom: 88px; left: 12px` relative to the outer compare-area wrapper. In the current split-always layout that hangs over the model pane and reads `mcStats`.
* The right pane paints from `ercotMcStats` / `ercotSppStats`, computed off SP values. Model buses vs SPs can have materially different congestion tails, so `+$X` on the two palettes maps to different colors.
* `Legend` owns (a) palette + ticks/anchor + optional LMP histogram, and (b) line-status key + residual Zones swatches. Only (a) is per-pane; (b) is model-side only.
* The app is split-always when `rightPaneFor(viewMode) !== "empty"`. For `binding_proximity` the right pane unmounts, so the ERCOT legend disappears with it.

## Approach

Files: `web/src/components/map/Legend.tsx`, `web/src/App.tsx`.

* **Step 1 — Legend variants** (`Legend.tsx`):
  * Add `variant?: "full" | "palette-only"` (default `"full"`) and `paneLabel?: string`.
  * `palette-only` skips the LMP histogram, the Zones swatch row, and the `legend__lines` block. Renders title, bar, ticks/labels/sub only.
  * Append `<div class="legend__pane-label label">` when `paneLabel` is set, styled 9px/uppercase to match `.pane-badge`.

* **Step 2 — mount the ERCOT legend** (`App.tsx`):
  * Inside the `rightPane` fragment, next to `pane-badge`, render a `<Legend variant="palette-only" paneLabel="ERCOT · SP anchor" …>` whose palette mirrors `rightKind` (MC → `ercotMcStats`; SPP → `ercotSppStats`).
  * Update the existing model-side `<Legend>` to pass `variant="full"` and `paneLabel="MODEL · bus anchor"` when the ERCOT pane is showing (`rightKind !== "empty"`), `undefined` otherwise.

* **Step 3 — positioning** (verify only):
  * `.compare-pane` sets `position: relative` (`CompareMap.tsx`), so the ERCOT legend's `position: absolute; bottom: 88px; left: 12px` anchors to the right pane. The model-side legend stays a sibling of `CompareMap` and anchors to the outer flex-1 wrapper — bottom-left of the model half. No layout code needed.

Do NOT touch: the Zones toggle (StatsPanel-owned), the residual Zones swatches, the PTDF halo row, or attempt to reconcile the two anchors — the point is to be honest about the difference.

## Acceptance

* [x] Two Legend widgets render when the ERCOT pane is mounted — model-side and ERCOT-side, each with its own `±p_high` ticks.
* [x] The ERCOT legend shows only palette + ticks + sub-line + pane label; no Zones swatches, no line-status swatches, no LMP histogram.
* [x] Model-side legend gains "MODEL · bus anchor" caption when the ERCOT pane is showing; caption is absent when `rightKind === "empty"` (binding proximity).
* [x] Switching to `binding_proximity` unmounts the ERCOT legend cleanly (it lives inside the `rightPane` fragment, which is replaced by `pane-empty`).
* [ ] Loading a window where ERCOT's |mc| P99 differs from the model's by ≥15% shows visibly different tick numbers on the two legends. *(Data-dependent — verify in dev server.)*
