# 0002 - redesign-layout

Type: refactor
Branch: `refactor/0139-matrix-redesign/0002-redesign-layout`
Source: `plan/0139-matrix-redesign/sprint-matrix-redesign.md`
Prototype: `docs/matrix_index_prototype.html` (this is the target UI — match it)
Depends on: 0001 (needs the full constraint-list endpoint for search)

## Goal

Rewrite the matrix workspace to match the prototype: a left index sidebar + a stage with a
`Read | SF` lens. Read is a stub in this branch (filled in 0003); the SF lens keeps the
existing grid.

## Files

* Edit: `web/src/workspaces/MatrixWorkspace.tsx` — owns state + URL, renders sidebar + stage.
* New: `web/src/components/matrix/MatrixSidebar.tsx` — tab + search + filters + list.
* Keep: `web/src/components/matrix/MatrixGrid.tsx`, `MatrixLegend.tsx` (rendered under SF lens).
* Edit: `web/src/lib/matrix.ts` — value-mode type.
* Delete: `web/src/components/matrix/MatrixInspector.tsx` and all its imports/usage.
* Data fetch: node list from `GET /analysis/settlement-points`; constraint list from the new
  `GET /analysis/constraints` (0002). Add both to `web/src/api/client.ts` + `types.ts`.

## State (in MatrixWorkspace)

```
tab:  "constraints" | "nodes"                    // default "constraints"
lens: "read" | "sf"                              // default "read"
val:  "sf" | "fmu" | "dmu"                       // default "sf"; only used when lens==="sf"
query: string                                    // single search box
fType: string                                    // "" = all
fZone: string                                    // "" = all
selection: {kind:"constraint",key} | {kind:"node",point} | null
pinnedConstraints: string[]                      // reuse existing pins
pinnedSettlementPoints: string[]
```

## URL contract (emit via existing `onSelectionRouteChange`; shell keeps t/ws/we/span/run)

* New params: `tab`, `lens`, `val`, `q`, `type`, `zone`.
* Keep: `constraint`, `sp`, `pinned_constraint` (repeatable), `pinned_sp` (repeatable).
* Back-compat: if `constraint_search` is present on load, read it into `query`.
* Only write non-default values (omit `tab=constraints`, `lens=read`, `val=sf`, empty q/type/zone).

## Steps

1. **Remove the inspector.** Delete `MatrixInspector` mount + `inspectorCollapsed` /
   `rememberedInspectorCollapsed` state. Clicking a row/col/cell now only sets `selection` +
   URL. Delete the file.
2. **Remove old discovery controls.** Delete the dual search inputs and the Rows / Type /
   Columns selects and their params (`rows`, `columns`, `ctype`, `sp_search`). Fold the old
   `constraint_search` into the single `query`.
3. **Build `MatrixSidebar`.** Props: `{tab, items, selectedId, onSelect, onTab, query, onQuery,
   fType, fZone, typeOptions, zoneOptions, onFilter, counts}`. Render: `Constraints | Nodes`
   segmented toggle; one search input; `All types` + `All zones` selects; a scrollable list.
   Each row shows id, a type tag, zone, and a size figure (constraints: daily Σμ; nodes: name).
   Clicking a row calls `onSelect` → sets `selection` + URL.
4. **Filter/sort the list client-side.** Filter items by `query` (constraint: match key/name/
   contingency; node: match point name), `fType`, `fZone`. Sort: constraints by daily-Σμ rank
   (from the endpoint); nodes by name.
5. **Lens toggle.** In the stage header render `Read | SF`. When `lens==="sf"` render the
   existing `MatrixGrid` + `MatrixLegend` (columns default to the pinned watchlist via the
   existing `columnSet`/pins). When `lens==="read"` render a stub:
   `<div>Read detail for {selection?.key ?? "…"} — built in 0003</div>`.
6. **SF value sub-toggle (1f).** Only when `lens==="sf"`, render `SF | Forecast μ | ERCOT DAM μ`.
   Map to existing math in `lib/matrix.ts`: `sf` = Shift Factor mode; `fmu` = Contribution
   with `muSource="forecast"`; `dmu` = Contribution with `muSource="ercotDam"`. Disable the
   DAM button when `frame.dam_status==="pending"` and fall back to `fmu` (keep existing guard).
7. **Landing.** On load with no `constraint`/`sp` param: `tab=constraints`, `lens=read`, select
   the top constraint by daily Σμ (first item in the sorted list).
8. **Placement.** All controls live in the workspace toolbar / sidebar — never in
   `components/layout/Header`.

## Do NOT touch

* `web/src/App.tsx` (scrubber ownership + `withCoord` merge), `api/matrix.py`, `Header`, Brief.
* The `/matrix/frame` grid contract — the SF lens keeps using it unchanged.

## Acceptance

* [x] Landing shows the sidebar + Read lens with today's top constraint selected — no random
      constraint, no inspector drawer. (No URL selection ⇒ the first item of the sorted list —
      constraints by `daily_mu_rank`, nodes by name — is used as the display default without a
      route write; an explicit click/URL selection always wins.)
* [x] `Constraints | Nodes` tab flips the sidebar list. The tab does not transpose the
      `/matrix/frame` rectangle (rows stay constraints, columns stay settlement points, per the
      "do not touch the grid contract" constraint below) — it flips which axis the *selection*
      targets, so a node pick highlights a grid column and a constraint pick highlights a row.
* [x] One search box + `All types` + `All zones` filter the full list from
      `/analysis/settlement-points` and `/analysis/constraints`. Old dual-search and
      Rows/Type/Columns controls are gone. Node type/zone (`/analysis/settlement-points` is a
      bare vocabulary list) come from a client-side merge with `/topology`'s `sp_type`/
      `load_zone`, fetched once — no backend change.
* [x] `Read | SF` toggles; SF shows the preserved grid; Read shows the 0003 stub.
* [x] Under SF only, `SF | Forecast μ | ERCOT DAM μ` appear; DAM disabled + falls back when
      `dam_status==="pending"`.
* [x] `tab/lens/val/q/type/zone/constraint/sp` + pins round-trip through the URL; an old
      `?constraint=…&constraint_search=…` link still resolves (`constraint_search` folds into
      `q`); the bottom scrubber still drives the hour and `t/ws/we` survive every state change
      (unchanged `withCoord` merge in `App.tsx`, not touched).
* [x] `MatrixInspector.tsx` is deleted and unreferenced.
