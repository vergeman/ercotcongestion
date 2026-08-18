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
* New: `web/src/api/analysisNode.ts` — the `/analysis/node` fetch+cache, keyed by
  `(point, deliveryDate, hour, basis, runId)`, mirroring `web/src/api/matrixFrames.ts`.
* Reuse as-is: `web/src/components/panels/ConstraintReach.tsx` (`Dipole`, `SfDipoleLegend`,
  `dipoleCounts`, `ConstraintReachStyles`, and the new `useFullConstraintReach` — see below),
  `web/src/components/brief/briefFormat.tsx` (`usd`, `percent`, `constraintName`, `zoneLabel` —
  already generic, no Brief-row coupling).
* Edit: `web/src/components/brief/BriefFootprintMap.tsx` — narrowed its prop from the full
  `BriefSelection` row union (which it never actually read past `geo`/`key`) to a minimal
  `FootprintTarget = {geo, key}`, and added an optional `onNavigate` intercept so a non-Brief
  caller can route the "Open in Map" click through its own in-app navigate instead of a bare
  `<Link>`. Brief's own call site (`BriefDetailPanel.tsx`) updated to pass `{geo, key}` — the
  panel's rendered output is unchanged (it never used any other row field).
* Edit: `web/src/api/client.ts` (`fetchMapReach` now takes an options object — `k`/`minFrac`/
  `full` — instead of a bare `k`), `web/src/api/types.ts` (`ConstraintReach.truncated`, the
  0139-0001 field that was never added to the frontend type).
* **Not reused as originally sketched**: `BriefDetailPanel.tsx`'s `ConstraintEvidence`/
  `NodeEvidence`/`HistoryBlock` are not lifted into a shared module. They are tightly coupled to
  Brief's own pre-aggregated row shapes (`TopConstraintRow`/`StandoutRow`/`TopNodeRow`/
  `NodeStandoutRow` — rank, one μ peak, one dominant driver + share), which is a fundamentally
  different, smaller data model than what this pane needs (the complete reach, the complete
  ranked driver column) and Matrix's full-vocabulary selections mostly don't have anyway (they
  fall outside Brief's own top-k). `MatrixReadDetail` writes its own evidence layout against
  `AnalysisConstraintRow` / the full `useFullConstraintReach` reach / `/analysis/node`'s `terms`
  instead. `BriefDetailPanel.tsx` itself is otherwise untouched — see the `BriefFootprintMap`
  prop-narrowing bullet above for its one line of edit.
* **History dropped for this pass**: Brief's 30-day `settled_history` arrays belong to those same
  Brief-specific rows and are keyed to Brief's top-k, not the Matrix search index's full
  vocabulary — there is no cheap, honest source of a history series for most Matrix selections
  without a new backend fetch. Rather than reuse Brief's arrays only for the lucky subset of
  selections that happen to overlap Brief's top-k (silently empty for everyone else), history is
  left out entirely, deferred to 0004 as the plan already anticipated.

## Steps

1. [x] **Scaffold `MatrixReadDetail`.** Props extended beyond the sketch — `{selection,
   timestamp, val, deliveryDate, runId, damStatus, constraintRow, nodeMeta, onNavigateToMap}`,
   sourced from state `MatrixWorkspace` already resolves (the frame's `delivery_date`/`run_id`/
   `dam_status`, and the selected row/metadata from the sidebar's own already-fetched lists) —
   so the detail pane does no identity fetching of its own, only reach/driver-column fetching.
   Renders the constraint variant when `selection.kind==="constraint"`, the node variant when
   `"node"`, else a "select something" hint. Wired into `MatrixWorkspace` where the 0002 stub was.
2. [x] **Constraint variant.** Added `useFullConstraintReach(key)` to `panels/ConstraintReach.tsx`
   (calls `fetchMapReach(key, {full: true, minFrac: 0})`, separately cached from the bounded
   `useConstraintReach` so a k=20 cache hit can never satisfy a full-reach request or vice versa).
   Renders the import/export dipole (`Dipole`/`dipoleCounts`, reused), a per-lobe member list
   sorted by |SF| with the top 8 inline and the rest behind a `<details>` tail (folded, not
   dropped), zone/kV/type/daily Σμ/binding hours from `AnalysisConstraintRow`. **Deviation**: no
   "μ peak" — `AnalysisConstraintRow` doesn't carry one and adding it would mean either a backend
   change (out of scope here) or wiring the unused `/analysis/forecast-mu` endpoint for one
   number; daily Σμ + binding hours cover the same "how strong/how often" question with data
   already in hand.
3. [x] **Node variant.** Fetches `/analysis/node` via the new `api/analysisNode.ts` cache, basis
   `predicted`/`realized` from `val`. Renders net congestion (`total`), SF coverage, ESSP member
   count (a light extra `/analysis/essp` fetch, silently absent when that hour has no ingested
   vintage), and the full ranked driver table (`constraint, SF, side, μ, $/MWh`) — the server
   already returns `terms` sorted by |contribution|, so no client re-sort. μ is not a field on
   `AnalysisContributionTerm`; derived exactly as `-contribution / shift_factor` (the same
   `contribution = -SF·μ` identity `lib/matrix.ts` already uses), `—` when `shift_factor` is 0
   (never true for a listed term — the backend already drops zero-contribution rows).
4. [x] **Share, don't copy — resolved as "mostly write fresh."** `ConstraintEvidence`/
   `NodeEvidence`/`HistoryBlock` turned out to be coupled to Brief's own pre-aggregated row
   shapes in a way that isn't just a props/typing inconvenience — Brief's model (one μ peak, one
   dominant driver, a rank) is categorically smaller than what this pane exists to show (the
   complete reach, the complete driver column), so there is no shared "evidence" to lift without
   inventing fake Brief rows. What genuinely was reusable *is* reused as-is (see Files): the
   reach hook/glyphs, the generic formatters, and `BriefFootprintMap` (narrowed to the minimal
   `{geo, key}` it actually reads — see Files). `BriefDetailPanel.tsx` needed exactly one line
   changed (`BriefFootprintMap`'s call site); its rendered output is unchanged.
5. [x] **Map.** `BriefFootprintMap` embedded for both variants; its "Open in Map →" button now
   accepts an `onNavigate` intercept (used here, wired to `onNavigateToMap` from the workspace
   prop chain) so the link carries the shared scrubber coordinate via `App.tsx`'s `withCoord`
   merge — a bare `<Link>` (Brief's own usage) would drop `t/ws/we/span/run` on navigation.
   Orientation + doorway only, per the constraint.
6. [x] **Scrubber.** The constraint variant has nothing hour-varying (reach is a run/window-level
   structural property, matching `useConstraintReach`'s existing no-hour-dependency behavior) —
   only day/run-level stats, keyed off `constraintRow`/`deliveryDate`, not `timestamp`. The node
   variant re-fetches on `[point, deliveryDate, timestamp, basis, runId]` via `AbortController` +
   a request-id guard (mirrors `MatrixWorkspace`'s own frame-fetch effect), cached by
   `(point, deliveryDate, hour, basis, runId)` in `api/analysisNode.ts`.
7. [x] **History — dropped, not deferred-with-a-stub.** See the Files section's explanation.
   Nothing renders where a history block would go; there is no placeholder claiming data that
   doesn't exist.

## Do NOT touch

* `App.tsx` scrubber ownership, `Header`, the SF grid from 0001, the backend (0002/0004).

## Acceptance

* [x] Constraint Read shows both import/export lobes (full reach, not the 15-node default) — via
      the new `useFullConstraintReach`, not `useConstraintReach`.
* [x] Node Read shows the full ranked driver column (`-SF·μ`) from `/analysis/node` — not the
      bounded/visible columns; μ derived client-side since the endpoint doesn't carry it per-term.
* [x] Evidence renders from the genuinely shared Brief pieces (reach glyphs, formatters,
      footprint map); `ConstraintEvidence`/`NodeEvidence` themselves are not reused (see step 4).
      The Brief panel is visually unchanged — verified by inspecting its one changed line.
* [x] The pane includes the footprint map + a working `/map` deep-link that carries the current
      scrubber coordinate.
* [x] Scrubbing updates the node column with no separate cursor and no stale/duplicate fetches
      (abort + request-id guarded); the constraint variant has no hour-varying content to update.
* [x] Node basis of μ follows `val` (Forecast vs DAM); DAM stays unavailable (never zero) — a
      live-data check confirmed `/analysis/node?basis=realized` returns `total: 0.0` even while
      `dam_status: "pending"` for that day, so the pane blocks the fetch itself on
      `damStatus==="pending"` rather than trusting the caller already guarded it.
