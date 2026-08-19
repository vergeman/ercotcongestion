# 0140 - header-nav-consistency

Type: feat
Branch: feat/0140-header-nav-consistency

## Goal

* Theme toggle + connection status, with date+time (was time-only), on every page.
* Scoreboard's "Backtest run" / "Window" / "Net-load Bucket" / all-hours dropdown
  move from the topbar to the main page, top-right of "Live · per-delivery-day
  grade" — replacing `{n_hours} h` next to `{n_nodes} nodes`.

## Context

* Map/Matrix (`Header.tsx`) had theme toggle + status dot; Brief/Scoreboard
  (bare `HeaderNav.tsx`) had neither, and status text was time-only everywhere.
* Neither Brief nor Scoreboard tracked a `connectionState`/`lastUpdated` pair
  (Scoreboard's fetch had no `.catch` at all) — `useExplorerSession.ts` is the
  reference pattern.
* Scoreboard's model-stat cluster lived in `sb-topbar` but is rendered by a
  separate component (`LiveGradePanel`), not `ScoreboardPage` itself — moving it
  requires prop-drilling, not just a JSX cut/paste.

## Approach (as built)

* New `web/src/components/layout/HeaderStatus.tsx` — self-contained theme toggle +
  status dot/label (date+time), taking `connectionState`/`lastUpdated` as props.
  Deliberately a sibling to `HeaderNav`, not folded into it: `Header.tsx`'s
  Map-only view/data toggles must sit between the nav and the status cluster,
  which a merged component couldn't preserve.
* `Header.tsx` renders `HeaderStatus` in place of its old inline block; dead CSS
  removed.
* `BriefPage.tsx` / `ScoreboardPage.tsx`: added `connectionState`/`lastUpdated`
  state, stamped in each page's existing fetch effect (Scoreboard's fetch gained
  a `.catch`, a real gap fix). Both render `HeaderStatus` in their topbar.
* `ScoreboardPage.tsx`: removed the meta cluster from `sb-topbar` (now just
  `HeaderNav` + `HeaderStatus`). `LiveGradePanel` gained `weekly`/`headlineWin`/
  `regime`/`onRegimeChange` props; the cluster now renders inside its
  `sb-live__head`, grouped with node count under a new `.sb-live__meta` wrapper.

## Acceptance

* [x] Theme toggle + status indicator render and work on all four pages.
* [x] "Updated" text shows date + time everywhere.
* [x] Scoreboard's `sb-topbar` has no model-stat cluster; it now sits top-right of
      "Live · per-delivery-day grade" next to `{n_nodes} nodes`; dropdown still
      filters correctly.
* [x] `tsc --noEmit -p web/tsconfig.app.json` clean.
* [x] Visual check in both dark and light themes on all four pages.
