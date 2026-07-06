# 0059 - ercot-pane-legend

Type: feat
Branch: feat/0059-ercot-pane-legend

## Goal

* Render a second Legend anchored to the ERCOT pane in split mode, driven by `ercotMcStats` — the model-side legend's anchor (`mcStats.p_high`) is not the same number as the ERCOT-side's, so a single legend misrepresents at least one pane.
* Show it only when split mode is active. In single or diff, keep the current behavior (one legend, over the main pane).
* Make the two legends visually distinguishable (small "MODEL" / "ERCOT" label under the palette bar) so a reader glancing at the split screen knows which anchor is which.

## Context

* `web/src/App.tsx:554-563` renders exactly one `Legend`, positioned absolute at `bottom: 88px; left: 12px` relative to the main map container (`Legend.tsx:286-295`). In split mode this legend hangs over the model pane and reads `mcStats`.
* The right pane paints from `ercotMcStats` (`App.tsx:203-204, 522`), computed off SP congestion values in the loaded window. The two anchors can differ materially — model buses can have congestion outliers the SP set does not, and vice versa — so `+$X` on the left palette and `+$X` on the right palette map to different colors.
* After plan 0058, `Legend` owns two concerns: (a) palette + ticks/anchor labels + optional LMP histogram, (b) line-status swatch key (binding / N-1 / PTDF) plus the residual Zones color swatches. Only (a) is per-pane; (b) is global-to-the-view. Do not duplicate (b) onto the ERCOT pane — the Zones swatches, PTDF halo key, and binding/N-1 swatches are all model-side concepts.
* Depends on plan 0058 having landed: `Legend.tsx` no longer accepts `onToggleZones`, and the toggle button lives in `StatsPanel`. If 0058 is not merged yet, this plan's `variant` split still works but reviewers should read it against 0058's post-state.
* Comparison mode is `single | split | diff` (`web/src/api/types.ts` — see `App.tsx:79`). The zone-diff palette (`isDiff` branch in `Legend.tsx:83-101, 216-237`) is a whole-view palette, not a per-pane one, so it stays on the model-side legend only.

## Approach

* Work in: `web/src/components/map/Legend.tsx`, `web/src/App.tsx`.
* Entry point / primary change: introduce a `variant: "full" | "palette-only"` prop on `Legend` and mount a second instance inside the right pane.

* **Step 1 — split Legend into two rendering modes** (`Legend.tsx`):
  * Add `variant?: "full" | "palette-only"` (default `"full"`) and `paneLabel?: string`.
  * When `variant === "palette-only"`: render only `legend__title`, `legend__bar`, and the ticks/labels/sub block. Skip the histogram (LMP is model-only), skip the Zones swatch row (still visible on the model pane via 0058's residual `.legend__zones-swatches` block), skip `legend__lines`. This isolates palette from the model-only keys.
  * Append a small caption row when `paneLabel` is set: `<div class="legend__pane-label label">{paneLabel}</div>` styled at 9px/uppercase, matching the pane badge already at `App.tsx:565-579`.
  * Keep the existing full-variant rendering (default) byte-for-byte for the model pane.

* **Step 2 — mount the ERCOT legend inside the right pane** (`App.tsx`):
  * Inside the `right={…}` fragment (`App.tsx:514-544`), next to the `pane-badge`, render:
    ```
    <Legend
      viewMode="modeled_congestion"
      buses={ercotBuses}
      lmpStats={null}
      mcStats={ercotMcStats}
      showZones={false}
      tightClusterIds={tightClusterIds}
      comparisonMode="single"
      variant="palette-only"
      paneLabel="ERCOT · SP anchor"
    />
    ```
  * Update the existing (model-side) Legend at `App.tsx:554-563` to pass `variant="full"` explicitly and `paneLabel={comparisonMode === "split" ? "MODEL · bus anchor" : undefined}`. In non-split modes the label stays off.

* **Step 3 — verify positioning inside the right pane**: the pane's positioned wrapper is `.compare-pane--half` (`CompareMap.tsx:40-45`), which sets `position: relative`. The legend's `position: absolute` therefore anchors to that pane, not the outer container. Confirm both legends sit at `bottom: 88px; left: 12px` of their own pane after mount.

* Do NOT touch: the Zones toggle (owned by StatsPanel post-0058), the residual Zones color swatches in Legend, the PTDF halo legend row, or the diff-mode branch — those stay single-instance on the model side. Do not attempt to reconcile the two anchors into a shared scale; the whole point of two legends is to be honest about the difference.

* Watch out for: in `single` and `diff` modes the right pane is unmounted (`CompareMap.tsx:28-33`), so the second legend disappears automatically — no explicit gating needed in App. But if the `right` prop is elaborated later (e.g. always-mounted right pane), gate on `comparisonMode === "split"` at the render site.

## Acceptance

* [ ] In `split` mode with a loaded window, two Legend widgets render — one anchored to the model pane, one to the ERCOT pane — each showing its own `±p_high` tick values.
* [ ] The ERCOT legend shows only the palette + ticks + sub-line + pane label; no Zones button, no line-status swatches, no LMP histogram.
* [ ] The model-side legend in `split` mode gains a "MODEL · bus anchor" caption; in `single` and `diff` it renders exactly as before (no caption).
* [ ] Switching from `split` → `single` unmounts the ERCOT legend cleanly (no orphaned DOM, no console warnings).
* [ ] Loading a window where ercot's |mc| P99 differs from the model's by ≥15% shows visibly different tick numbers on the two legends — verifies the two-anchor path.
* [ ] Diff mode still renders exactly one legend (the model-side, diff palette). No ERCOT legend appears.
