# 0003 - detail-pane

Type: feat
Branch: `feat/0139-matrix-redesign/0003-detail-pane`
Source: `plan/0139-matrix-redesign/sprint-matrix-redesign.md`
Prototype: `docs/matrix_index_prototype.html` (Read-lens panel is the target)
Depends on: 0002 (Read stub + lens) and 0001 (`/analysis/node`, `/analysis/constraints`)

## Goal

Replace the Read-lens stub with real detail: a constraint's reach (import/export lobes) and a
node's full driver column. Reuse the Brief detail components; add the footprint map; confirm
the pane follows the scrubber.

## Files

* New: `web/src/components/matrix/MatrixReadDetail.tsx` — constraint + node variants.
* Reuse (extract shared parts if Brief-coupled): `web/src/components/brief/BriefDetailPanel.tsx`  <!-- 0002 built the stub this replaces -->
  (`ConstraintEvidence`, `NodeEvidence`, `HistoryBlock`),
  `web/src/components/panels/ConstraintReach.tsx` (`useConstraintReach`),
  `web/src/components/brief/BriefFootprintMap.tsx`.
* Edit: `web/src/api/client.ts`, `web/src/api/types.ts`, and a small `analysisNode` fetch+cache
  (mirror `web/src/api/matrixFrames.ts`).

## Steps

1. **Scaffold `MatrixReadDetail`.** Props `{selection, timestamp, val}`. Renders the constraint
   variant when `selection.kind==="constraint"`, the node variant when `"node"`, else a
   "select something" hint. Wire it into `MatrixWorkspace` where the 0001 stub was.
2. **Constraint variant.** Use `useConstraintReach(selection.key)` (call with `min_frac=0`,
   `full=true` per 0001 — the unbounded reach, not the `k`-limited display call). Render the
   import/export dipole, top members per lobe, μ peak, binding hours — reuse
   `ConstraintEvidence`. Fold sub-threshold nodes into a collapsed tail (do not drop them at
   the API).
3. **Node variant.** Fetch `GET /analysis/node?settlement_point={point}&delivery_date={ctDate}
   &hours=[{timestamp}]&basis={predicted if val!=="dmu" else realized}`. Render net congestion,
   coverage, ESSP, and the full ranked driver table (`constraint, SF, side, μ, -SF·μ`) sorted
   by |contribution| — reuse `NodeEvidence`. This is the full column, not the bounded frame.
4. **Share, don't copy.** If `ConstraintEvidence` / `NodeEvidence` / `HistoryBlock` are coupled
   to Brief props, lift the shared body into an importable module and have both Brief and Matrix
   render it. The Brief panel must look identical after.
5. **Map.** Embed `BriefFootprintMap` for the selection, plus the deep-link to `/map` via
   `onNavigateToMap` (from 0001). Orientation + doorway only — not a second interactive map.
6. **Scrubber.** Derive every time-varying value (μ, contribution, DAM status, node column, map
   hour) from the `timestamp` prop. Re-fetch the node column when `timestamp` changes; cache by
   `(point, ctDate, hour, basis)` and abort stale requests during fast scrubbing.
7. **History.** Use whatever window 0004 exposes; if 0004 hasn't landed, use the existing 30-day
   series the Brief shows.

## Do NOT touch

* `App.tsx` scrubber ownership, `Header`, the SF grid from 0001, the backend (0002/0004).

## Acceptance

* [ ] Constraint Read shows both import/export lobes (full reach, not the 15-node default) from
      `useConstraintReach`.
* [ ] Node Read shows the full ranked driver column (`-SF·μ`) from `/analysis/node` — not the
      bounded/visible columns.
* [ ] Evidence renders from shared Brief components; the Brief panel is visually unchanged.
* [ ] The pane includes the footprint map + a working `/map` deep-link.
* [ ] Scrubbing updates μ, contribution, DAM status, and map hour with no separate cursor and no
      stale/duplicate fetches.
* [ ] Node basis of μ follows `val` (Forecast vs DAM); DAM stays unavailable (never zero).
