# 0221 - scoreboard-history-cadence-separation

Type: fix
Branch: fix/0221-scoreboard-history-cadence-separation

## Goal

* Return weekly walk-forward and final served-daily Scoreboard histories as distinct API series.
* Render the two cadences in separate chart sections so neither is interpolated, connected, or equally spaced with the other.
* Make the latest served-grade comparison show its signed model-minus-persistence delta explicitly.

## Context

* The 0219 backfill correctly replaces only `scoreboard_daily` metric values using each forecast's immutable served SF artifact; it does not modify forecasts, SF artifacts, weekly scores, API code, or web code.
* `ScoreboardHistory` currently flattens `scoreboard_weekly` and every final `scoreboard_daily` row into `points`, while `SeriesChart` ignores `cadence`, gives each point equal x-spacing, and joins a source across the weekly/daily boundary.
* More repaired daily rows made this pre-existing presentation defect visible; daily grades are not weekly walk-forward observations and must not be presented as one continuous track.
* A negative value in the live comparison is a model-minus-persistence delta, not a negative persistence metric; rank Spearman may mathematically be negative, but current stored persistence values are non-negative.

## Approach

### Commit 1 — Make history cadence explicit in the API contract

* Work in: `api/schemas/scoreboard.py`, `api/services/scoreboard.py`, `api/tests/test_scoreboard_history.py`, and `api/tests/test_scoreboard_summary.py`.
* Entry point / primary change: replace the flattened `ScoreboardHistory.points` response field with distinct `weekly_points` and `served_daily_points` collections, retaining `weekly_run_id`, `daily_run_id`, and source descriptors.
* Build `weekly_points` exclusively from the already-resolved `ScoreboardWeekly.points`; build `served_daily_points` exclusively from horizon-1 rows for the independently selected latest daily run, ordered by delivery date and source.
* Remove `cadence` and `boundary_date` when the separate collections make them redundant. Preserve each point's native date field (`week` or `delivery_date`) and source/series identity.
* Preserve the existing availability behavior: a weekly board still returns history when there are no final daily grades, with an empty served-daily collection and `daily_run_id=None`.
* Update API tests to assert no flattened history field exists, no H2 rows leak into served history, separate run provenance is retained, and weekly-only history remains valid.
* Do NOT touch: `scoreboard_daily` values, the 0219 backfill, `grade_forecast_day`, `forecast_nodal`, `forecast_sf_artifact`, `scoreboard_weekly`, or score formulas.

### Commit 2 — Render weekly and served history as separate Scoreboard sections

* Work in: `web/src/api/types/scoreboard.ts`, `web/src/features/scoreboard/SeriesChart.tsx`, `web/src/pages/ScoreboardPage.tsx`, `web/src/features/scoreboard/LiveGradePanel.tsx`, relevant Scoreboard CSS, and focused web tests if the project has coverage for these components.
* Entry point / primary change: pass `history.weekly_points` and `history.served_daily_points` to independently rendered chart sections rather than concatenating them.
* Make `SeriesChart` accept one cadence's points and its native time label. Render the weekly chart only from weekly observations and the served chart only from daily observations; do not draw a boundary connector or label intended to bridge the two.
* Keep source colors, metric controls, tooltips, and direct labels consistent across both charts. Show a clear empty state for the served section when final grades are unavailable; do not hide the weekly track record.
* Update page copy to call the sections “Walk-forward weekly backtest” and “Final served daily grades,” replacing language that calls the combined output one track record.
* In `LiveGradePanel`, retain the model, persistence, and Oracle values but display an explicit signed `Δ vs persistence` value (for example, `−0.14`) alongside the direction indicator so it cannot be read as a negative persistence score.
* Ensure each chart has a metric-appropriate y-domain. Do not claim rank Spearman is constrained to `[0, 1]`; support its valid `[-1, 1]` range or a domain that includes all returned values.
* Do NOT alter the API's score values in the browser, coerce negative rank values, aggregate daily grades into weekly values, or re-run/backfill any data as part of this presentation fix.

### Commit 3 — Verify the boundary and communicate the data contract

* Work in: `docs/METRICS.md` and any Scoreboard copy that describes the chart history.
* Document that weekly walk-forward scores and daily served grades are independent cadences and may use different run IDs; they are comparable only within their own score definitions and are deliberately displayed separately.
* Confirm the 0219 served-SF explanation remains unchanged: daily source rows are projected through their exact stored served artifact, while weekly rows retain their walk-forward map contract.
* Exercise the bundled `/scoreboard/summary` endpoint against a fixture or local board containing both cadences and inspect that each chart receives only its own date grain.

## Acceptance

* [x] `/scoreboard/summary` returns separate weekly and served-daily history collections with independent run IDs; it no longer returns a cadence-mixed flat point sequence.
* [x] Horizon-2 and non-selected daily-run rows never appear in the served-daily chart collection.
* [x] A Scoreboard with only weekly rows renders the weekly chart and a clear unavailable/empty served-daily section without failure.
* [x] With both datasets present, the UI renders two charts with no line joining the final weekly observation to the first daily grade and no equal-spacing mix of weeks and days.
* [x] The latest live card explicitly labels model-minus-persistence as a signed delta, while displaying persistence's own score separately.
* [x] Focused API tests and web lint/typecheck/build pass; database tables and values are unchanged by this work.
