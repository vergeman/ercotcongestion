# 0007 - scoreboard-page-presentation

Type: refactor
Branch: refactor/0160-frontend-api-architecture-refactor/0007-scoreboard-page-presentation
Base: merged `0006-brief-page-presentation`
Source: `plan/0160-frontend-api-architecture-refactor/README.md`
Depends on: 0001, 0002, 0003

## Goal

* Separate live-grade, backtest, controls, chart, glossary, and responsive layout responsibilities.
* Avoid refetching data that is invariant for a user control change.
* Move the page’s inline styles to feature-owned styles without altering chart interaction.

## Context

* `web/src/pages/ScoreboardPage.tsx` is 1,269 lines and contains visualization math, fetch state, live/backtest composition, glossary markup, and a large style block.
* `/scoreboard/summary` bundles weekly, headline, and daily responses; changing regime or horizon re-fetches fields unaffected by one of those controls.
* The live panel and backtest board have distinct domain state and can render independently.

## Approach

* Work in: `web/src/pages/ScoreboardPage.tsx`, new `web/src/features/scoreboard/*`, `web/src/api/scoreboard.ts`, and feature styles.
* Use `useScoreboard` from 0003 to expose independently cached live-grade and backtest resources, following the API contract decisions in 0001.
* Extract `ScoreboardControls`, `LiveGradePanel`, `BacktestHeadline`, `BacktestSeries`, `BacktestSplitTable`, and `ScoreboardGlossary`; preserve existing chart SVG/accessibility behavior behind narrow props.
* Put metric/group/horizon transitions in a controls reducer, keeping request state out of the visual controls.
* Move chart measurement/hover logic into `useScoreboardChart` and test coordinate clamping plus keyboard/pointer behavior.
* Move inline page CSS to feature styles and retain responsive two-pane/one-column layout behavior.
* If 0001 does not yet expose split live/backtest resources, keep `/scoreboard/summary` as a compatible fallback; do not couple deployability to a new API rollout.

## Acceptance

* [x] Regime changes refetch only backtest resources; horizon changes refetch only live-grade resources when the API supports that split.
* [x] Live and backtest failure/empty states render independently.
* [x] Chart hover, end labels, metric switches, glossary, and responsive layout remain behaviorally equivalent.
* [x] `ScoreboardPage` primarily composes feature sections and no longer contains the page’s request implementation and style sheet.
* [x] `npm run build`, lint, and Scoreboard chart/control tests pass from this branch alone.
