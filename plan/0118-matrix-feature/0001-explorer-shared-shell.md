# 0001 - explorer-shared-shell

Type: refactor
Branch: `refactor/0118-matrix-feature/0001-explorer-shared-shell`
Source: `plan/0118-matrix-feature/sprint-matrix.md`

## Goal

* Extract the shared forecast window, timestamp cursor, connection state, and playback controls from the current map application.
* Render the existing map as `MapWorkspace` inside a route-aware `ExplorerShell`.
* Add a `/matrix` placeholder that uses the same live shell and single `PlaybackScrubber`.
* Preserve current map behavior and appearance.

## Dependency and merge position

* This is the first branch in the Matrix sprint and has no dependency on another Matrix branch.
* Merge while Matrix is still a placeholder. This isolates state ownership and routing changes from the new data contract and visualization.
* The scorecard remains a separate analytical application outside the explorer shell.

## Required context

* The finished explorer must allow users to move between `/map` and `/matrix` without losing the loaded window or selected hour.
* `web/src/App.tsx` currently owns route-specific rendering and shared playback state, while also mixing map-only controls, data fetching, hover/pin state, and map rendering.
* `web/src/main.tsx` performs minimal pathname switching, and current header links navigate as full page loads.
* Full document navigation would recreate the loaded window and cursor, defeating the shared-instrument behavior.
* `web/src/api/prefetch.ts` caches the nodal forecast/realized playback window. Future dense Matrix frames require a separate bounded cache; do not add them to this cache.

## Product invariants

* Keep the existing map and its Constraints tab.
* Add `/matrix`; do not embed a second map in the Matrix.
* Render exactly one shared `PlaybackScrubber` below either explorer workspace.
* Preserve query parameters so later branches can deep-link constraints and settlement points.
* Keep `/scoreboard` on its standalone path.

## Approach

* Work primarily in:
  * `web/src/App.tsx`
  * `web/src/main.tsx`
  * `web/src/components/layout/`
  * new `web/src/pages/` or `web/src/workspaces/` modules
* Extract a `useExplorerSession` hook or equivalent provider owning:
  * loaded date window;
  * available timestamps;
  * `currentIndex` and current timestamp;
  * window loading/prefetch action;
  * connection and last-updated state;
  * sparkline series and active curated event; and
  * props required by `PlaybackScrubber` and `DateRangePicker`.
* Keep map-only state in `MapWorkspace`, including map mode, palette, topology, constraint overlays, map cards, and map-specific ranked-list controls.
* Mount `PlaybackScrubber` once in `ExplorerShell`, beneath the active workspace.
* Add lightweight client-side route state for `/map` and `/matrix` with `history.pushState` and `popstate`. Add a small router only if implementation planning demonstrates a real need.
* Give the header an active Map/Matrix navigation contract and a slot or configuration point for workspace-specific controls.
* Preserve the current pathname/query string contract on direct loads and client navigation.

## Out of scope

* Matrix API/data fetching, matrix rendering, selection, hover metadata, discovery controls, or a second map.
* Moving Matrix data into the nodal `prefetchWindow` cache.
* Refactoring the standalone scoreboard into the explorer shell.

## Acceptance

* [x] `/map` renders the same map modes, cards, constraints, legend, and side panel as before the refactor.
* [x] `/matrix` renders a deliberate placeholder inside the same header and playback shell.
* [x] Switching Map → Matrix → Map preserves the date window and selected timestamp.
* [x] Browser back/forward restores the correct workspace without a document reload.
* [x] A direct load of `/map`, `/matrix`, or `/scoreboard` resolves correctly.
* [x] Exactly one `PlaybackScrubber` is mounted in either explorer route.
* [x] Existing API requests are not duplicated solely because the user switches workspaces.
* [ ] TypeScript build and the repository's canonical frontend checks pass in a clean, supported Node environment. Docker Compose build passes; the canonical lint command still reports pre-existing `setState`-in-effect errors and one hook-dependency warning outside this refactor.

## Merge boundary

Merge when the Matrix remains a placeholder and the shared shell, route transitions, and existing map behavior are independently verified.
