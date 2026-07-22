# 0110 - web-unified-tooltip

Type: refactor
Branch: refactor/0110-web-unified-tooltip

## Goal

* Add a shared `Tooltip` component replacing native `title=` bubbles app-wide.
* Migrate the scoreboard `Term` popovers onto `Tooltip`.
* Align the map `grid-tooltip` chrome to the shared tooltip look.

## Context

* Styled tooltip pattern existed only on `ScoreboardPage` (`sb-term__pop`).
* Rest of the app used native `title=` (or its own popover).

## Approach

* Work in: `web/src/components/ui/Tooltip.tsx`, `web/src/index.css`.
* Entry point: `Tooltip` — renders trigger via `as`, portals `.tt` bubble to `<body>` (fixed, flip + clamp).
* Convert the 19 `title=` sites across `App`, `ScoreboardPage`, `ConstraintPanel`, `SidePanel`, `DetailCard`, `Header`, `HeaderNav`, `DateRangePicker`.
* Rewrite `Term` as a `Tooltip` wrapper; delete dead `sb-term__pop` CSS.
* Restyle `.grid-tooltip` to `.tt` tokens (keep maplibre popup mechanism).
* Remove row-hover tooltips in `DetailCard` rows and `ConstraintPanel` rows; keep column-header and control tooltips.

## Acceptance

* [x] No non-aria `title=` remain in `web/src`.
* [x] `Term` and `grid-tooltip` render through the shared `.tt` style.
* [x] No row-hover tooltips in DetailCard / Constraints rows; all four Constraints column headers have tooltips.
* [x] `tsc` clean (pre-existing GridMap errors only); no new eslint errors.
