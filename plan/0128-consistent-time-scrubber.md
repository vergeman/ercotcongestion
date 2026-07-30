# 0128 - consistent-time-scrubber

Type: feat
Branch: feat/0128-consistent-time-scrubber

## Goal

* Drive Map, Matrix, and Analysis from one shared time coordinate in the URL (`?t` hour, `?span` view, `?run`, `?ws`/`?we` window).
* Render a single `PlaybackScrubber` — Load Window + play + step + sparkline — identically on all three pages.
* Keep the scrubber present on Analysis even when no brief exists for the cursor (content area shows the empty state, transport stays).

## Context

* Done: extracted `TimeTransport` from `PlaybackScrubber` (transport vs domain); added `useTimeCursor` (`?t/?span/?run/?ws/?we`) + `snapToFrames`; `App`/`useExplorerSession` read the cursor+window on mount and mirror the live index back; `HeaderNav` carries the coordinate; Analysis derives its day from the cursor with an explicit empty state.
* Gap: `useExplorerSession` (live window + prefetch) is mounted per-`App`; Analysis mounts outside it and uses a play-less `TimeTransport` over the brief's 24 hours — so it has no Load Window/play and disappears when there is no brief.
* Constraint: Analysis has briefs only for `available_dates`; the live window need not overlap. Consistency is of the *coordinate*, not of the data — a cursor on a day with no brief is a valid empty state.

## Approach

* New: `web/src/hooks/useSharedExplorer.tsx` (`ExplorerProvider` + `ExplorerLayout` + `useSharedExplorer` consumer), `web/src/components/playback/ExplorerScrubber.tsx`. Edit: `web/src/main.tsx`, `web/src/App.tsx`, `web/src/pages/AnalysisPage.tsx`, `web/src/components/playback/PlaybackScrubber.tsx`.
* Session lifted to a **layout route**: `main.tsx` nests Map/Matrix/Analysis under `<ExplorerLayout>` (which mounts `ExplorerProvider` = one `useExplorerSession` + URL-coordinate two-way sync). The layout element stays mounted across those child routes, so the window/cursor/data persist — no refetch on navigation. Scoreboard is a sibling, outside it.
* Pages consume the session via `useSharedExplorer()` (context) and each mount the shared `ExplorerScrubber` (PlaybackScrubber + Load Window + play + optional `rightSlot`).
* `PlaybackScrubber`: add a `rightSlot` passthrough (Analysis whole-day toggle).
* Analysis: derive the shown day from the cursor's CT day; render the scrubber always (even with no brief); body shows brief-or-empty. Removed the bespoke `TimeTransport` + canonicalizer.
* Reuse existing coordinate machinery (`useTimeCursor`, `snapToFrames`, `?t/?span/?run/?ws/?we`) — no new URL params.
* Do NOT touch: modeling/API, brief JSON shape, Scoreboard (no scrubber for now), the map-kept-mounted trick in `App`.

## Acceptance

* [x] One `PlaybackScrubber` (Load Window + play + step + spark) via shared `ExplorerScrubber` on Map, Matrix, and Analysis.
* [x] Analysis renders the scrubber even with no brief; body shows "No Insight Brief for <day>".
* [x] `tsc --noEmit -p web/tsconfig.app.json` clean.
* [ ] Scrubbing on any page updates `?t` (+`?ws`/`?we`); navigating lands on the same hour/window (manual click-test).
* [ ] Analysis: walking hours keeps the day, flips the day page at midnight; whole-day toggle works (manual click-test).
* [ ] Map → Analysis → Map preserves window + cursor (manual click-test).
* [ ] Switching Map ↔ Analysis does NOT refetch / show a loading flash — session persists via the layout route (manual click-test).
