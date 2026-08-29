# 0178 - simplify scoreboard live-grade panel

Type: refactor
Branch: refactor/0178-simplify-scoreboard-live-grade-panel

## Goal

* Show the latest final served grade as the sole live-grade summary.
* Remove the delivery-date selector and preview/final track selector from the Scoreboard page.
* Make historical daily investigation happen through the unified score-history graph.

## Context

* `ScoreboardPage` already fetches all daily rows but uses local state and a dropdown to select one day.
* After 0177, every daily final grade is available in the main graph, so duplicating date navigation in the tile panel adds little value.
* The product scorecard should describe the final forecast actually served; h2 preview remains stored for audit and other analysis, not this primary surface.

## Approach

* Work in: `api/scoreboard.py`, `api/models.py`, `api/tests/test_scoreboard_daily.py`, `web/src/api/types.ts`, `web/src/api/scoreboard.ts`, `web/src/hooks/useScoreboard.ts`, `web/src/pages/ScoreboardPage.tsx`, scoreboard CSS, focused web tests, and `docs/Scoring.md`.
* Entry point / primary change: add/use a latest-final-grade response (or a `latest_only` server reduction) and make `LiveGradePanel` stateless with respect to date and horizon.
* Select the newest fully persisted h1 delivery date and all its comparator rows in SQL/API rather than downloading a full daily history merely to choose its first date in React. Return the selected date and final-horizon provenance explicitly.
* Remove `day` state, date `<select>`, horizon state/selector, h2 labels, and horizon query threading from the Scoreboard page. Render the selected date as compact provenance next to the tiles.
* Keep loading/empty/error behavior truthful: if no h1 grade exists, leave the panel absent or show the existing unavailable state while retaining the historical chart; do not silently fall back to h2.
* Update page copy and documentation to direct readers to graph hover/keyboard interaction for prior daily grades. Coordinate this change after 0177 so the graph provides that history first.
* Do NOT delete: `scoreboard_daily.horizon`, preview forecast/grading jobs, or APIs used by non-Scoreboard consumers without an explicit consumer audit.

## Acceptance

* [x] The live panel displays exactly the newest h1 grade and its delivery date with no date or horizon dropdown.
* [x] The Scoreboard page makes no h2 request and never substitutes preview results for a missing final grade.
* [x] Historical daily final grades remain inspectable in the 0177 unified graph.
* [x] Focused API and web tests cover latest selection, missing-final behavior, and removal of both selectors.
