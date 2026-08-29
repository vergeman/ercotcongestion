# 0177 - unify backtest and live score history

Type: feat
Branch: feat/0177-unify-backtest-and-live-score-history

## Goal

* Extend the Scoreboard trend graph from the historical walk-forward backtest into daily grades of served forecasts.
* Preserve the provenance and cadence boundary between weekly backtest points and daily final-track grades.
* Make the graph advance automatically whenever `grade_day` persists a new final grade.

## Context

* `scoreboard_weekly` stops at the last manually loaded offline walk; production currently ends on 2026-07-15.
* `grade_day` already appends comparable `score_matrix` screening currencies to `scoreboard_daily` every day; final h1 grades begin on 2026-07-18 and are current.
* The page has weekly, headline, and daily primitive resources, but its load path
  is now consolidated through `/scoreboard/summary`.

## Approach

* Work in: `api/scoreboard.py`, `api/models.py`, `api/schemas/scoreboard.py`, `api/tests/test_scoreboard*.py`, `web/src/api/types.ts`, `web/src/api/scoreboard.ts`, `web/src/hooks/useScoreboard.ts`, `web/src/pages/ScoreboardPage.tsx`, `web/src/features/scoreboard/useScoreboardChart.ts`, and scoreboard-focused web tests.
* Entry point / primary change: add `history` to the existing `/scoreboard/summary`
  response. Build it internally from immutable weekly points and final-horizon
  daily points; do not add a separate public chart endpoint.
* Define one explicit chronological contract: weekly points use `week`, daily points use `delivery_date`, and every point carries `source`, `cadence` (`backtest_weekly` or `served_daily`), score currencies, and denominator metadata. Use h1/final only; never interleave h2 preview values into the product track record.
* Resolve the weekly and daily run IDs independently and expose both in provenance. Keep a visible boundary marker and labels/tooltip text explaining that points before it are walk-forward backtest weeks and points after it are served daily forecasts.
* Have the chart render one ordered time axis with weekly historical values followed by daily values. Retain model, persistence, climatology, and oracle; tolerate absent sources/metrics without joining unrelated runs or fabricating a bridge point.
* Make the Scoreboard page fetch `/scoreboard/summary` once per selected live
  horizon. Keep the weekly split/table on its weekly-only response section;
  `WeeklyPoint` remains a compatibility field on the established weekly resource.
* Add API tests for ordering, h1-only selection, empty-live fallback, independent
  run provenance, and summary composition. Validate chart compilation and retain
  pointer/keyboard selection across both cadences.
* Do NOT touch: the offline backtest job/schedule, `scoreboard_weekly` ingestion, `grade_day` calculation semantics, or preview-horizon storage.

## Acceptance

* [x] The trend graph ends at the latest available h1 `scoreboard_daily` grade rather than at the final offline-backtest week.
* [x] Every displayed history point is labeled/inspectable as either weekly walk-forward backtest or daily served grade, with an explicit transition boundary.
* [x] The `/scoreboard/summary` history section never mixes h2 preview grades into the final track and handles unavailable daily grades without failing the historical chart.
* [x] The page makes one `/scoreboard/summary` request per selected live horizon; API tests cover chronological composition, provenance, h1 selection, and summary composition, and the web build validates the chart changes.
