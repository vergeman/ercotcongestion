# 0104 - web-styling-polish

Type: fix
Branch: refactor/web-stylings

## Goal

* Post-font-swap UI polish and layout fixes across the map and scoreboard pages.
* Grouped into independently-revertable commits.

## Context

* Follows the Inter/JetBrains font swap + casing + size-bump staging point.
* Item "legacy product terms" (modeled congestion / binding → Forecast Error) is **out of scope** here — tracked in `0105`.

## Already applied (branch `refactor/web-stylings`)

* `1b275c3` — light/dark theme + CSS design-token scale.
* `c60e297` — centralize bespoke Barlow font spacing into `index.css` (revert-friendly Phase 1).
* `be913cd` — restyle with Inter/JetBrains: uppercase reserved for headers, sentence-case labels, unified scoreboard font, global size bump.

## Approach

### Commit 1 — Legend + DetailCard theme toggle (fix)

* Work in: `web/src/components/map/Legend.tsx`, `web/src/components/map/DetailCard.tsx`
* Both are stuck in dark mode — replace hardcoded colors with theme tokens (`var(--bg-*)`, `var(--text-*)`, `var(--border*)`) so they follow light/dark.

### Commit 2 — Unified header + nav (fix)

* Work in: `web/src/components/layout/Header.tsx`, `web/src/pages/ScoreboardPage.tsx`
* Same `ERCOT STRESS` brand on both map and scoreboard pages.
* Replace per-page description with nav links: `Map`, `Scoreboard`, `Analysis` (inactive/disabled — not yet built).
* Map: remove the header subtitle entirely.
* Scoreboard: move the header subtitle to the right, add labels denoting what the terms mean.

### Commit 3 — Map pane subtitle legibility (fix)

* Work in: `web/src/App.tsx` (pane badge / `predictionLabel` / `errorLabel`)
* Enlarge the `Congestion forecast error · model · dataset · # SP …` subtitle slightly.
* Add labeling so each term is self-explanatory (both forecast-error and dual views).

### Commit 4 — Equal-thirds layout (refactor)

* Work in: `web/src/index.css` (`--panel-w`), `web/src/App.tsx` layout
* Widen the side panel, shrink the map by the same amount — target equal thirds as a starting point.

### Commit 5 — Scoreboard table sizing (fix)

* Work in: `web/src/pages/ScoreboardPage.tsx`
* Enlarge the table 1–2px to use the surrounding whitespace.

### Commit 6 — Playback Scrubber layout + button (fix)

* Work in: `web/src/components/playback/PlaybackScrubber.tsx`, `web/src/components/playback/DateRangePicker.tsx`
* Make the `📅 Load Window` button text consistent with the other buttons (drop bespoke `--text-mono`/inline sizing).
* Move transport controls to the left, below the Load Window button; raise the Load Window button.
* Reduce the overall Playback Scrubber height.

## Acceptance

* [x] Legend + DetailCard follow the light/dark toggle.
* [x] Both pages share the `ERCOT STRESS` header with `Map` / `Scoreboard` / `Analysis`(disabled) nav; map header subtitle removed; scoreboard subtitle right-aligned + labeled.
* [x] Map pane subtitle is larger and its terms are labeled (titles reworded to Prediction Model / ERCOT DAM / Forecast Error; label-first counts with hover notes on the forecast/priced asymmetry).
* [x] Side panel and map render as ~2/7 : the rest (pulled back from a full third; constraint table re-spaced with px columns).
* [x] Scoreboard table is enlarged and fills its whitespace (chart right-margin widened so end-labels don't clip; rolling-window note moved to the topbar with a tooltip).
* [x] Load Window button matches sibling buttons and spans the transport cluster; scrubber controls sit left below it (stacked play/pause + centered steppers); component is shorter.
