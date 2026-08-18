# 0139 - matrix-redesign (sprint)

Type: refactor
Source prototype: `docs/matrix_index_prototype.html`

## Why

* The live `/matrix` opens on a random constraint at an arbitrary hour, defaults to a
  sparse SF grid that reads as "vague," and can only surface top-K rows/columns — you
  must leave for the map to find anything else.
* The app already owns the constraint→nodes / node→constraints attribution three ways
  (Brief tables, `BriefDetailPanel`, map sidebar). The matrix should stop competing with
  those and instead be the one thing missing: **a complete, name-searchable index of the
  full constraint & node universe that pivots into that existing 1-D detail — with the
  recovered shift factors as a toggled showcase lens.**

## Product shape (what we are porting from the prototype)

* **Left sidebar = the index.** A searchable, filterable list of the *full* universe
  (not top-K), with a `Constraints | Nodes` tab that flips the axis.
* **Two lenses over the same search:**
  * **Read** (default) — pivots the selected row into the reach / lobe / driver detail
    that already exists (`useConstraintReach`, `BriefDetailPanel` evidence).
  * **⚡ Shift factors** — the current SF grid, preserved; columns are the pinned
    watchlist so it is dense by construction. Value sub-toggle: `SF | Forecast μ |
    ERCOT DAM μ` (the existing SF/Contribution + μ-source machinery, re-presented).
* Entry lands on **today's top constraint by Σμ** in Read — never blank, never random.

## Invariants every branch must preserve

* **Shared time cursor.** The bottom `ExplorerScrubber` (owned by `App.tsx`) is the only
  time source; the matrix consumes `timestamp={timestamps[currentIndex]}`. Do NOT fork a
  local cursor. All time-varying values (μ, contribution, DAM status, the detail pane)
  follow the scrubbed hour.
* **URL is the shareable state.** Continue emitting state through
  `onSelectionRouteChange(search)` → the shell's `withCoord` merges it with
  `t/ws/we/span/run`. Keep the existing grammar backward-compatible
  (`?constraint=`, `?sp=`, `?constraint_search=`) so old links resolve, and add
  `?tab`, `?lens`, `?val` (SF|fmu|dmu). Pins stay in `?pinned_constraint` /
  `?pinned_sp` + `ercotstress.matrix-pins.v1` localStorage.
* **Preserve from the current build:** SF↔Contribution + Forecast/DAM μ math
  (`lib/matrix.ts`), import/export color convention (color by −SF), the day-stable
  legend scale, the bounded frame LRU cache (`api/matrixFrames.ts`), and the
  `matrix.py` artifact/day-resolution + DAM-μ join + type/zone metadata.
* **Never imply** recovered implied SF is an official ERCOT PTDF.

## Sequence (branch = one plan; file order = build order)

* `0001-backend-full-vector.md` — (api) add `/analysis/constraints` (full constraint list);
  verify `/analysis/node` single-hour + predicted/realized; document the `/map/reach`
  full-reach call. No deps — land first.
* `0002-redesign-layout.md` — (web) sidebar index + search/filter + `Read | SF` lens + SF
  value sub-toggle; remove the old inspector + discovery controls. Read = stub. Needs
  0001's `/analysis/constraints`.
* `0003-detail-pane.md` — (web) fill the Read pane (reach lobes + full node column), share
  Brief components, add the map, track the scrubber. Needs 0001 + 0002.
* `0004-history-window.md` — (api) OPTIONAL: extend the trailing history window if cheap,
  else document the cap. No deps; 0003 works without it.
* `0005-augmented-design.md` — (api + web) SF-lens prototype parity: `orientation` param so the
  tab rotates the grid axes, ≤5 rows/cols + hub/max-μ default seeds, one pin model shared across
  sidebar and grid headers, and sidebar↔grid selection scroll-sync (which also resolves the
  reported "matrix constraints missing from the sidebar" confusion — a UI ordering/locator issue,
  not a data fault). Builds on 0001–0003.

Build straight down: 0001 → 0002 → 0003. 0004 any time (or skip). 0005 after 0003.
