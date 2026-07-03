# Sprint 3 — Frontend comparison view

Goal: reality next to model; scorecard in Stats; clusters as point tags.
Depends on S1 (zone data) + S2 (scorecard endpoint).

**Current state:** single MapLibre pane (`web/src/components/map/GridMap.tsx`);
view pills in `Header.tsx` drive `ViewMode` in `App.tsx`
(`modeled_congestion|lmp|congestion_vs_basis|binding_proximity`); right panel tabs
Stats/Validation (`App.tsx`); no zone/cluster layer; no ERCOT SP layer.

## S3.1 — Retire Validation tab, fold scorecard into Stats (D10)
- **Files:** `web/src/App.tsx` (remove `panelTab` Stats/Validation split + tab CSS),
  delete/absorb `components/panels/ValidationPanel.tsx`, extend
  `components/panels/StatsPanel.tsx`.
- **Do:** StatsPanel gains a **cluster scorecard list**: per zone row {name, corr,
  sign%, rank, dispersion}, click → highlight zone on map. Consume S2.2 endpoint.

## S3.2 — Cluster point-tag rendering (F2)
- **Files:** `GridMap.tsx`, `components/map/Legend.tsx`, `lib/colors.ts`.
- **Do:** color the 5–7 named tight zones; everything else gray background blob.
  Membership interaction-driven: hover/click a zone in the StatsPanel list →
  members get halo + full opacity (`circle-stroke` / feature-state), others dim
  to ~20%. Centroid name labels when zones layer on. **No polygons** (or hulls
  only for pinned zone). Add a Congestion↔Zones layer toggle.

## S3.3 — Three-mode comparison (F1)
- **Files:** new `comparisonMode` state in `App.tsx`; `GridMap.tsx` (second synced
  instance); new ERCOT SP source; zone-diff fill layer.
- **Modes:**
  - **Split (default):** two synced MapLibre panes, shared camera + time cursor
    (maplibre `syncMaps` or manual `on('move')` mirror). Left = model buses (per-bus
    congestion fill), right = ERCOT SPs (actual congestion fill). Same diverging
    scale/legend.
  - **Single:** current single pane, model- or ERCOT-only.
  - **Diff:** choropleth zones by `model_Z(t) − ercot_Z(t)` at scrubber hour
    (from S2 per-hour series). Green≈agreement, diverging = over/under-predict.
- **Replace** the view pills with the mode switch.

## S3.4 — Data plumbing
- **Files:** `web/src/api/client.ts`, `prefetch.ts`, `types.ts`.
- **Do:** fetch ERCOT SP snapshot fills + zone geometry/labels + per-hour
  `model_Z`/`ercot_Z`. Extend prefetch window loader to carry ERCOT side.

## Acceptance
- Split view renders model | ERCOT synced on the scrubber.
- Diff view choropleths zone agreement per hour.
- StatsPanel shows the cluster scorecard; Validation tab gone.
- Zone membership legible via hover halo/dim, not 12 border colors.
