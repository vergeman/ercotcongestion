# 0196 - Map day-scoped scorecard

Type: feat
Branch: feat/0196-map-day-scoped-scorecard

## Goal

* Replace the Map SidePanel's stale 30D/90D offline-backtest headline with the selected delivery day's final served Scoreboard grade.
* Fall back to one explicitly labelled offline weekly backtest row only when no final served grade exists for that day.
* Preserve source provenance so model, persistence, and oracle values always describe the displayed scorecard basis.

## Context

* `SidePanel` currently receives `ScoreboardHeadline` from `/map/summary` and presents 30D/90D weighted offline-weekly rollups.
* `scoreboard_daily` already contains per-delivery-day, settled h1 grades written by `compute.jobs.grade_forecast_day`.
* A historical map cursor has a CT delivery day; its scorecard should follow that day, not the newest manually refreshed weekly backtest.
* Daily and weekly source IDs differ but share logical model/persistence/climatology/oracle series identities.

## Approach

* Work in: `api/schemas/map.py`, `api/services/map/`, `api/routes/map.py`, `web/src/api/map.ts`, `web/src/api/types.ts`, `web/src/workspaces/MapWorkspace.tsx`, and `web/src/components/panels/SidePanel.tsx`.
* Commit 1 — Add a map-specific, day-scoped scorecard schema and service. Given a CT delivery date and forecast run, query all h1 `scoreboard_daily` comparator rows for that exact day; normalize daily source IDs to the display/series contract and return the three screening metrics plus `basis="served_daily"`, grade date, horizon, and availability state.
* Commit 1 — When that complete final-grade set is unavailable, query one coherent latest `scoreboard_weekly` source set, normalize it through the same contract, and return `basis="weekly_backtest_fallback"` with its scored week. Do not blend daily and weekly sources or silently substitute h2.
* Commit 1 — Expose the service through a date-parameterized Map endpoint, using the same CT delivery-day normalization as the cursor/artifact paths. Return an explicit unavailable response when neither a daily grade nor a weekly fallback exists.
* Commit 2 — Remove `headline` from the Map bootstrap composition and its `MapSummaryResponse` consumer path if it becomes unused; retain the Scoreboard endpoint and `ScoreboardHeadline` unchanged for the Scoreboard page.
* Commit 2 — Request the scorecard whenever `MapWorkspace`'s `deliveryDay` changes, cancel stale requests, and pass the resulting day-scoped payload to `SidePanel`.
* Commit 2 — Replace the 30D/90D toggle and backtest-only presentation with a compact source comparison labelled either `Final served grade · <delivery date>` or `Offline backtest fallback · week of <week>`. Show the exact selected/fallback date and never label fallback data as current forecast performance.
* Commit 3 — Add API/service tests for final h1 preference, h2 exclusion, incomplete daily-set fallback, no-data behavior, CT date selection, and daily/weekly source normalization. Add focused UI tests for day changes, provenance labels, and removal of the 30D/90D controls.
* Do NOT touch: `compute.jobs.grade_forecast_day`, `scoreboard_weekly` materialization, Brief grading, or the Scoreboard page's independent 30D/90D headline.

## Acceptance

* [x] Moving the Map cursor to a settled delivery day displays that day's h1 model, persistence, and oracle metrics from `scoreboard_daily`; it refreshes when the cursor crosses a CT delivery-day boundary.
* [x] A day without a complete final grade displays only a clearly dated `Backfill · week of <week>` row; h2 is never shown as final.
* [x] The Map SidePanel has no 30D/90D control or wording implying a rolling current-performance summary; internal run IDs remain in the API response but are not shown.
* [x] The Scoreboard page retains its existing weekly 30D/90D headline behavior.
* [x] API/service tests cover source selection, h1 preference, h2 exclusion, incomplete daily fallback, no-data behavior, CT date selection, and source normalization; the production web build passes.
