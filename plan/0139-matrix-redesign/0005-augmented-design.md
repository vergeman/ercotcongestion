# 0005 - augmented-design (SF-view prototype parity)

Type: feat
Branch: `feat/0139-matrix-redesign/0005-augmented-design`
Source: `plan/0139-matrix-redesign/sprint-matrix-redesign.md`
Prototype: `docs/matrix_index_prototype.html` (the **SF lens** is the target this time)
Depends on: 0001 (`/analysis/*`), 0002 (sidebar + lens), 0003 (Read detail). Builds on the
shipped 0139 stack; no new plan depends on this one.

## Goal (as shipped)

The SF lens is a **working set** the user curates, not an auto-ranked grid:

1. **One stable rotation set, transposed in the client.** A single frame holds the working set
   (rows=constraints, cols=nodes on the wire). The `Constraints | Nodes` tab transposes it
   client-side (`matrixDisplayAxes(frame, orientation)`); it **never refetches or re-selects**.
2. **Seed once, then user-owned.** First load seeds the working set from the defaults —
   constraints ranked by **anchor contribution** (`|μ_cursor| × Σ|SF| over anchors`, blank-anchor
   rows dropped) × the curated **`DEFAULT_ANCHORS`** hubs/zones — and pins them to
   `ercotstress.matrix-pins.v1` with a `seeded` marker. Thereafter the frame is pin-driven
   (`row_preset=pinned`, `column_set=pinned`). Emptying the set by hand stays empty on reload
   (respect-empty); **Reset to defaults** clears `seeded` and re-seeds.
3. **Top row = live preview.** Clicking a sidebar entry selects it and hoists it to row 1; if not
   pinned it rides in via **`peek`** (a forced row/column beyond the pin cap) with a dashed
   header + hollow star. Pinning **prepends** it to the top of the working set (no re-sort); the
   next preview pushes it to row 2. The hoist is coupled to the displayed frame (`frameTopKey`
   fallback) so a still-loading preview never drops to the bottom and shifts the grid.
4. **Pins are localStorage-only** (dropped from the URL to keep links short; old links with
   `pinned_*` are still read). Grid header stars and sidebar stars share the same two pin sets;
   a star targets the entity's own kind, correct in either orientation.

Recorded resolution of the "missing constraints" bug (§Background): a discoverability problem,
now moot — every entity is reachable by search/preview, and selecting one previews it directly.

Backend also carries an unused-by-UI `orientation=nodes` node-major branch + hub seed (kept as a
tested capability; the client transposes instead).

## Background — the "constraints in the matrix don't exist in the sidebar" report

Investigated live against the running API (`/matrix/frame` vs `/analysis/constraints`,
run `mu-all-v1`, delivery days 2026-08-12…14). **Findings, so we don't re-chase this:**

* **Not a data bug.** Every constraint the report named exists in the sidebar universe:
  `POT_PEAR_1` → `POT_PEAR_1|SMOOPEA8`; `NLARSW_PILONC1_1` → four contingency keys;
  `WESTEX` → `WESTEX|BASE CASE`. Across daytime *and* evening hours, **0 of 30** matrix rows
  were absent from the sidebar list.
* **Same universe by construction.** A stored artifact reindexes `E_mu` onto `SF.index`
  (`compute/sf/project.py:194` — `E = E_mu.reindex(columns=SF.index)`), so the matrix's row
  source (`artifact.SF.index`) and the sidebar's source (`/analysis/constraints` →
  `artifact.E_mu.columns`) are identical sets. `SF.index == E_mu.columns` always.
* **The real cause is ordering + no locator.** The matrix ranks rows by
  **contribution (Σ|μ| × Σ|SF| reach)**; the sidebar ranks by **Σ|μ| alone**. The matrix's
  visible top rows land at sidebar ranks 2, 4, 6, 7, 8, 14, 21, 29, … — scattered through the
  1029-item list and interleaved with high-Σμ / low-reach constraints the matrix never shows.
  With **no scroll-to-selected in the sidebar** and duplicate display names across
  contingencies, a selected matrix row never reveals itself in the list and the top of the
  sidebar looks like a different set entirely.
* The evening UTC-block-vs-CT-date artifact concern (see memory `utc-block-cut-and-evening-leak`)
  was checked and does **not** produce visibly missing rows: adjacent-day constraint
  vocabularies overlap enough that a one-day artifact shift still resolves every visible key.

**Therefore the fix for the "bug" is item 4 (scroll-sync) plus item 3 (shared pin state), not a
data repair.** An optional sidebar sort by the matrix's contribution metric (§Optional) further
reconciles the two orderings.

## Design decisions

### Orientation lives in the backend; the payload stays SF-native; the grid transposes rendering

`/matrix/frame` gains `orientation=constraints|nodes` (default `constraints`,
backward-compatible). **What it changes is the selection logic, not the wire shape:**

* The response `rows` are **always** constraints (`MatrixRow`), `columns` are **always**
  settlement points (`MatrixColumn`), and `sf.values` stays constraint-major row-major. A cell
  is unambiguously `SF[constraint, node]` in every orientation — the SF math never flips.
* A new `orientation` field is echoed on the frame. The **client** reads it to decide the visual
  axis: `constraints` renders rows=constraints / cols=nodes (today's layout); `nodes` renders
  rows=nodes / cols=constraints by transposing at draw time in `MatrixGrid`.
* The param's real job is **which axis gets the "primary list" treatment** (ranking + search +
  `row_limit`, becoming the display rows) vs. the **"pinned secondary" treatment** (pins +
  default anchor, becoming the display columns):

  | orientation | primary/list axis (display rows) | secondary/pinned axis (display cols) |
  |---|---|---|
  | `constraints` | constraints, ranked by contribution + `constraint_search` | nodes: `pinned_settlement_point` + **hub default** |
  | `nodes` | nodes, ranked by max\|SF\| vs. shown constraints + `settlement_point_search` | constraints: `pinned_constraint` + **max-μ-at-cursor default** |

This honors "backend orientation param" (the server genuinely selects node-major rows, ranked
and bounded — the thing a pure client transpose could not do well) while keeping serialization
and the SF cell identity single-sourced. The client transpose is *rendering only*, over an
already-correct rectangle.

### Node-row ranking (nodes orientation)

Cheap and cursor-stable: for the chosen constraint columns `C`,
`node_score = artifact.SF.loc[C].abs().max(axis=0)`, take the top `row_limit`. Nodes most
strongly driven by the shown constraints float up; pins and search are force-included on top.
(Rationale: a per-node `−Σ SF·μ` net-congestion rank is the "truer" ordering but costs a full
projection per node; max\|SF\| vs. the shown columns is the same signal the constraint-major
`core_max` column ranking already uses, reused on the other axis.)

### Default column seeds (item 2)

Only applied when the user has **no pins on the column axis yet**, so the grid opens non-empty
and the seed disappears the moment the user pins something.

* **columns = nodes** (constraints orientation): one **hub**. Pick the hub SP
  (`_sp_metadata` type `'hub'`) with the largest max\|SF\| against the visible constraint rows;
  fall back to the first hub in the artifact if none score. Never invent a node.
* **columns = constraints** (nodes orientation): the constraint with the largest **\|ERCOT DAM μ\|**
  at the cursor hour, or **\|forecast μ\|** when DAM is pending/partial (mirrors the val-source
  fallback the rest of the SF lens already uses).

Row cap and column cap both default to **5** for the SF lens (new `rowLimit`/`columnLimit`
defaults from the workspace; the backend `DEFAULT_*` constants are unchanged so other callers
keep 30/40). Pins and search matches are still force-included beyond the cap, exactly as the
existing `_append_bounded` reserve logic does.

### Unified pin model (item 3)

Pins already exist as two URL/localStorage sets — `pinnedConstraints` /
`pinnedSettlementPoints` (`?pinned_constraint` / `?pinned_sp`, `ercotstress.matrix-pins.v1`).
Keep those two sets; make **both** the sidebar star and new **grid header stars** write to them:

* A pin star on a **row header** toggles the row entity's pin (keeps it in the ≤5 bounded view).
* A pin star on a **column header** toggles the column entity's pin (this is the prototype's
  `✕`/`+ pin` on columns).
* Sidebar stars and grid stars are the same state — pinning in one lights the star in the other.
* "Pin to both node/constraint depending on the view" falls out naturally: in constraints
  orientation, row stars hit `pinnedConstraints` and column stars hit `pinnedSettlementPoints`;
  in nodes orientation the two swap. No third pin concept is introduced.

### Selection scroll-sync (item 4, and the item-5 remedy)

* **Grid already scrolls to selection** (`MatrixGrid` effect on `selection`, `scrollIntoView`).
  Keep it; it must follow the transposed ids in nodes orientation.
* **Add sidebar scroll-to-selected**: `MatrixSidebar` scrolls its list to `selectedId` whenever
  it changes (a row `ref` + `scrollIntoView({block:"nearest"})`), guarded so it fires on
  selection change, not on every keystroke/filter.
* Net effect: choosing a matrix row reveals it in the sidebar and vice versa — the concrete cure
  for the "it's not in the sidebar" confusion.

## Backend changes (`api/matrix.py`, `api/models.py`)

* `api/models.py`: add `orientation: Literal['constraints','nodes'] = 'constraints'` to
  `MatrixFrame`. No change to `MatrixRow`/`MatrixColumn`/`MatrixSfValues`.
* `api/matrix.py`:
  * Accept `orientation: str = Query('constraints', pattern='^(constraints|nodes)$')`.
  * Factor the current constraint-major selection into the `orientation=='constraints'` branch,
    adding the **hub default column** seed when `pinned_settlement_point` is empty.
  * Add the `orientation=='nodes'` branch: constraint **columns** = `pinned_constraint` +
    max-μ-at-cursor default (bounded by the same `_append_bounded` reserves); node **rows** =
    `settlement_point_search` matches + `pinned_settlement_point` + top-`row_limit` by
    `SF.loc[C].abs().max(axis=0)`. Build `rows`/`columns`/`values` from the same `artifact.SF`
    slice (still constraint-major on the wire), set `orientation='nodes'`, and populate
    `rows_truncated`/`columns_truncated`/`total_*` against the correct universes.
  * `values` stays `row_sf.loc[row_keys, column_keys]` (constraint rows × node cols); the client
    transposes for display. `dam_status`, legend extrema, and metadata paths are unchanged.
* `api/tests/test_matrix.py`: cover both orientations — node-major row selection, the two
  default seeds (present when unpinned / replaced when pinned), pins forced past the ≤5 cap,
  search on each axis, and `orientation` echo. Keep the existing constraint-major assertions
  green (default request unchanged).

## Frontend changes

* `web/src/api/types.ts`: add `orientation` to the `MatrixFrame` type.
* `web/src/api/client.ts` + `web/src/api/matrixFrames.ts`: thread `orientation` through
  `MatrixFrameRequest`, the query string, `normalizedBounds`, and **both cache keys**
  (`requestKey` + `matrixFrameCacheKey`) so a constraints frame can't satisfy a nodes request.
* `web/src/lib/matrix.ts`: no new SF math; add a small `matrixDisplayAxes(frame)` helper that
  returns `{ displayRows, displayColumns, transposed }` so the grid and workspace agree on the
  visual orientation in one place.
* `web/src/components/matrix/MatrixGrid.tsx`:
  * Render display rows/cols from `matrixDisplayAxes` (transpose when `orientation==='nodes'`);
    cell value lookup stays `SF[constraint,node]` regardless of which axis is visual-row.
  * Add **pin stars** to row and column headers (`onTogglePin(entity, axisKind)`), styled like
    the sidebar star; wire the existing header click to select, star click to pin (stopPropagation).
  * Keep `selectionElementId`/`scrollIntoView`; make ids follow the transposed axis.
  * Tooltip content picks constraint-vs-node body by the entity kind, not by row/col position.
* `web/src/components/matrix/MatrixSidebar.tsx`: add scroll-to-`selectedId` (row ref +
  effect); grid stars and sidebar stars share `onTogglePin`.
* `web/src/workspaces/MatrixWorkspace.tsx`:
  * Request the frame with `orientation = state.tab === 'nodes' ? 'nodes' : 'constraints'`,
    `rowLimit: 5`, `columnLimit: 5`.
  * Map tab → orientation so toggling the sidebar tab rotates the grid (item 1).
  * Route pin toggles from both sidebar and grid into the existing
    `pinnedConstraints`/`pinnedSettlementPoints` sets; the axis a star hits depends on
    `state.tab` (§Unified pin model).
  * On selection change, drive both scrolls (grid via its own effect, sidebar via `selectedId`).
  * `MatrixLegend`/corner axis label already reads "constraint ↓ \ node →"; flip the wording by
    orientation.

## Steps (build order)

1. [x] Backend: `orientation` param + `MatrixFrame.orientation`; constraint-/node-major branches,
       node-row ranking, hub + max-μ seeds. (node-major branch shipped but unused by the UI.)
2. [x] Frontend plumbing: types, client, `matrixFrames` cache keys, `matrixDisplayAxes` helper.
3. [x] `MatrixGrid`: orientation-aware transpose + tooltip-by-kind; ids follow axis; pin stars.
4. [x] Sidebar scroll-to-selected; grid↔sidebar scroll-sync.
5. [x] Pivot to the working-set model: `DEFAULT_ANCHORS` column set + `anchor_contribution` row
       order + `peek` param (backend, tested); seed-once + localStorage `seeded` + Reset-to-defaults,
       top-row preview, prepend-on-pin, frame-coupled hoist, pins out of URL (frontend).
6. [ ] Manual browser pass: seed on fresh load; preview→pin lands at top with no shift; unpin/reload
       respects empty; Reset re-seeds; tab transposes without refetch.

## Do NOT touch

* `App.tsx` scrubber ownership / shared time cursor; the Read (Detail) lens and its components
  from 0003; the `lib/matrix.ts` SF↔contribution + μ-source math; the import/export color
  convention; the bounded-frame LRU cache mechanics (only its key gains `orientation`).
* Never imply the recovered implied SF is an official ERCOT PTDF.

## Acceptance

* [ ] Toggling Constraints/Nodes transposes the same frame client-side (no refetch); the corner
      names the row axis.
* [ ] Fresh load seeds the working set from the defaults (`anchor_contribution` × `DEFAULT_ANCHORS`,
      no blank-anchor rows) and persists it; unpinning to empty stays empty on reload; **Reset to
      defaults** re-seeds.
* [ ] Clicking a sidebar entry previews it at row 1 (dashed/hollow-star) with no grid shift while it
      loads; pinning prepends it to the top (no re-sort); the next preview pushes it to row 2.
* [ ] Grid + sidebar stars share the two pin sets; a star targets the entity's own kind in either
      orientation. Pins are localStorage-only; the URL stays short; old `pinned_*` links still resolve.
* [x] Default (no `orientation`) `/matrix/frame` requests unchanged; `test_matrix.py` passes (21).

## Optional (only if cheap; else defer)

* A sidebar **sort** control (`Σμ | contribution | name`) so the list can match the matrix's
  contribution ordering directly, matching the prototype's `sort` select. Scroll-sync already
  makes items findable, so this is a nicety, not required for acceptance.
