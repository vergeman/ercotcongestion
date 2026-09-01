# 0197 - Remove Scoreboard rolling headline

Type: refactor
Branch: refactor/0197-remove-scoreboard-headline

## Goal

* Remove the deprecated 30D/90D weekly headline from the Scoreboard API and page.
* Retain weekly backtest history, pooled weekly summaries, served daily grades, and the Map fallback.

## Context

* `scoreboard_headline` computes the 30D/90D weighted rollups.
* The Map now uses its own day-scoped scorecard and no longer consumes the headline.
* `scoreboard_weekly` remains the source for the Map fallback and Scoreboard history.

## Approach

* Work in: `api/schemas/scoreboard.py`, `api/services/scoreboard.py`, `api/services/scoreboard_headline.py`, `api/models.py`, `api/tests/`, `web/src/api/types.ts`, `web/src/hooks/useScoreboard.ts`, and `web/src/pages/ScoreboardPage.tsx`.
* Commit 1 — Remove `ScoreboardHeadline` schemas, `scoreboard_headline` service, and the `headline` section from the Scoreboard summary contract and composition. Delete its dedicated tests and compatibility exports.
* Commit 2 — Remove the 30D/90D headline types, hook state, and Scoreboard-page tiles. Keep weekly chart, pooled splits, daily grades, and source provenance intact.
* Commit 3 — Update focused API and UI coverage to assert the reduced summary payload while preserving weekly backtest and daily-grade rendering.
* Do NOT touch: `scoreboard_weekly` materialization, Map scorecard fallback selection, or daily grade production.

## Acceptance

* [x] `/scoreboard/summary` has no `headline` field and no rolling 30D/90D computation remains.
* [x] The Scoreboard page has no 30D/90D headline tile or wording.
* [x] Weekly chart/splits, served daily grades, and Map weekly fallback continue to use `scoreboard_weekly` as before.
* [x] Focused API and web tests pass.
