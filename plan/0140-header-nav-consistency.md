# 0140 - header-nav-consistency

Type: feat
Branch: feat/0140-header-nav-consistency

## Goal

* Move the theme toggle + connection-status indicator out of `Header.tsx` and into
  the shared `HeaderNav.tsx`, so Brief and Scoreboard render them too (today only
  Map/Matrix get them).
* Extend the "updated" status text to show date + time everywhere, not time-only.
* Wire Brief and Scoreboard's own fetch state into that status indicator (each page
  derives its own `connectionState`/`lastUpdated` — there is no shared session on
  these routes).
* On Scoreboard, move the page-specific model stats ("Backtest run", "Window",
  "Net-load Bucket", the all-hours `<select>`) out of the topbar/nav area and onto
  the main page, top-right of the "Live · per-delivery-day grade" section — replacing
  the `{n_hours} h` text next to `{n_nodes} nodes`, which stays.

## Context

* `Header.tsx` (used only by Map/Matrix) owns the theme toggle and status dot
  (`Header.tsx:122-162`); `HeaderNav.tsx` (used directly by Brief and Scoreboard, and
  wrapped by `Header`) has neither — those two pages show only the bare nav strip.
* Status text is time-only today (`lastUpdated.toLocaleTimeString()`,
  `Header.tsx:159`) on the pages that have it at all.
* Neither Brief nor Scoreboard currently tracks a `"ok"|"error"|"loading"` union or a
  `lastUpdated` timestamp — Brief has `loading`/`error` booleans/string
  (`BriefPage.tsx:1418-1424`) to derive from; Scoreboard has only `loading`
  (`ScoreboardPage.tsx:803`) and no `error` state at all (fetch has no `.catch`).
  `useExplorerSession.ts:29-30` is the reference pattern for both derived state shape.
* Theme is a single global source of truth (`data-theme` on `<html>`, set by
  `lib/theme.ts`) — the toggle button works identically regardless of which
  component renders it, no per-page opt-in needed.
* Scoreboard's model-stat cluster (`ScoreboardPage.tsx:843-916`) lives inside
  `sb-topbar`, visually part of the header row even though it's not in `HeaderNav`.
  The target location — `sb-live__head` (`ScoreboardPage.tsx:455-477`) — already
  right-aligns its last child via `.sb-live__ctx { margin-left: auto }`, so this is a
  JSX relocation within the same component, not a state lift (`weekly`, `headlineWin`,
  `regime`, `REGIMES` are all already in scope there).

## Approach

### Group 1 — shared status indicator in HeaderNav

* Work in: `web/src/components/layout/HeaderNav.tsx`, `web/src/components/layout/Header.tsx`
* Move the theme-toggle button and status-dot/text block (`Header.tsx:122-162`,
  plus their `<style>` rules ~`Header.tsx:197-215`) into `HeaderNav.tsx`. Leave
  `Header.tsx`'s mobile-menu button where it is — that's Map/Matrix-specific chip-control
  collapsing, not shared chrome.
* Add required props to `HeaderNav`: `connectionState: "ok" | "error" | "loading"`,
  `lastUpdated: Date | null` (making them required, not optional, forces every call
  site to supply real values — `tsc` will flag any that don't).
* Update the "updated" text to include the date, e.g.
  `` `updated ${lastUpdated.toLocaleDateString()} ${lastUpdated.toLocaleTimeString()}` ``
  — apply this once in `HeaderNav` so all four pages inherit the same format.
* `Header.tsx` forwards its existing `connectionState`/`lastUpdated` props straight
  into the `HeaderNav` it wraps instead of rendering the toggle/status itself.

### Group 2 — wire Brief and Scoreboard

* Work in: `web/src/pages/BriefPage.tsx`, `web/src/pages/ScoreboardPage.tsx`
* Brief: derive `connectionState = error ? "error" : loading ? "loading" : "ok"` from
  the existing state at `BriefPage.tsx:1418-1424`. Add a `lastUpdated` state, stamped
  with `new Date()` on fetch completion in the effect around `BriefPage.tsx:1473-1480`.
  Pass both into `<HeaderNav active="brief" .../>` (`BriefPage.tsx:1632`).
* Scoreboard: add an `error` state (none exists) with a `.catch` on the fetch effect
  at `ScoreboardPage.tsx:803-826`. Add a `lastUpdated` state stamped the same way.
  Derive `connectionState` the same as Brief. Pass both into
  `<HeaderNav active="scoreboard" .../>` (`ScoreboardPage.tsx:839`).

### Group 3 — relocate Scoreboard's model stats

* Work in: `web/src/pages/ScoreboardPage.tsx`
* Remove the `sb-meta`/`sb-meta--sub`/`sb-regime` block (`ScoreboardPage.tsx:843-916`)
  from `sb-topbar`, leaving that header with just `<HeaderNav .../>` — matching
  Brief's bare topbar.
* Move that block into `sb-live__head` (`ScoreboardPage.tsx:455-477`), replacing the
  `` {model?.n_hours != null ? ` · ${model.n_hours} h` : ""} `` segment of
  `.sb-live__ctx`. Keep `{n_nodes} nodes`.
* Adjust `.sb-topbar` / `.sb-meta` / `.sb-live__head` / `.sb-live__ctx` CSS
  (`ScoreboardPage.tsx:1009-1034`, `1094-1097`, `1126-1129`) only as needed for the
  new layout — the flex-wrap + `margin-left:auto` pattern already there should carry
  over with minimal change.
* Do NOT touch: the `REGIMES` data/filtering logic itself, `run_id`/`window_days`/`weeks`
  values, or Brief's own body-level date controls (`an-day-controls__date`) — those
  are unrelated to this header work.

## Acceptance

* [ ] Theme toggle renders and works (persists via `localStorage`, flips
      `data-theme`) on Brief and Scoreboard, matching Map/Matrix.
* [ ] Status indicator (dot + label) renders on Brief and Scoreboard, reflecting each
      page's own real fetch state — verify by throttling/erroring a request in
      devtools and watching the dot change.
* [ ] "Updated" text shows date + time on all four pages.
* [ ] `Header.tsx` no longer duplicates toggle/status markup — it forwards props to
      `HeaderNav`, which is the single render site.
* [ ] Scoreboard's `sb-topbar` contains only `HeaderNav`; the model-stat cluster no
      longer appears there.
* [ ] Backtest run / Window / Net-load Bucket / all-hours dropdown render top-right
      of "Live · per-delivery-day grade", next to `{n_nodes} nodes`, replacing the old
      `{n_hours} h` text; the dropdown still filters correctly.
* [ ] `tsc --noEmit -p web/tsconfig.app.json` clean.
* [ ] Visual check in both dark and light themes on all four pages.
