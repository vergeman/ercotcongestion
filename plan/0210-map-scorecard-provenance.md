# 0210 - Map scorecard provenance

Type: fix
Branch: fix/0210-map-scorecard-provenance

## Goal

* Show an ungraded h1 forecast as `Final score pending` with no metrics.
* Use weekly backtest metrics only for the selected historical scored week.

## Context

* `/map/scorecard` currently substitutes the newest `scoreboard_weekly` row for every missing daily grade.
* This makes a pending Sep. 14 h1 grade appear as an unrelated July backfill.
* `scoreboard_weekly` is the one-time historical walk-forward record; it avoids rebuilding two years of daily served grades.

## Approach

* Work in: `api/schemas/map.py`, `api/services/map/scorecard.py`, `api/tests/test_map_scorecard.py`, `web/src/api/types/map.ts`, and `web/src/components/panels/SidePanel.tsx`.
* Return the exact complete h1 `scoreboard_daily` set first.
* When h1 forecast rows/artifact exist for the requested day and run but its grade is incomplete, return an explicit pending state with no score sources; do not fall back.
* Otherwise, select only a complete weekly set whose scored seven-day block contains the requested date, and label it as a historical backtest. Return unavailable if none exists.
* Render pending and unavailable states without metric values; retain the existing final-grade table and the historical-backtest table.
* Do NOT touch: forecast/grade scheduling, `scoreboard_weekly` generation, or rebuild historical daily grades.

## Acceptance

* [x] A published, ungraded h1 forecast shows `Final score pending` and no July-style substitute metrics.
* [x] A historical day without a daily grade uses only its date-aligned weekly backtest; a day outside that coverage is unavailable.
* [x] Complete h1 daily grades remain preferred, and h2 rows never appear as final grades.
* [x] Focused API tests cover final, pending, historical-backtest, and unavailable states; web lint and build pass.
