# 0218 - range-window-guardrails

Type: fix
Branch: fix/0218-range-window-guardrails

## Goal

* Reject explorer date ranges that are reversed or exceed two weeks.
* Prevent oversized URL windows from issuing range API requests.
* Enforce the same two-week limit at every range API endpoint.

## Context

* The Load Window picker and `ws`/`we` URL restoration currently pass arbitrary dates to the shared explorer session.
* `/ercot_range`, `/forecast_range`, and `/conditions_range` have no span or ordering validation; the latter materializes one entry per requested hour.
* `MAX_STATE_RANGE_HOURS` already defaults to 336 (14 days), but none of these routes use it.

## Approach

### Commit 1 — validate explorer windows in the web client

* Work in: `web/src/components/playback/DateRangePicker.tsx`, `web/src/hooks/useExplorerSession.ts`, and focused web coverage or an extracted pure range helper's test.
* Add one shared client validator for valid `Date` values, `start <= end`, and an elapsed span no greater than 336 hours; use it before custom-load requests and URL-restored windows reach `prefetchWindow`.
* Keep the picker open and display an accessible, actionable validation message for an invalid custom range; for an invalid URL window, set the session error state and issue no range requests.
* Treat exactly 14 days/336 hours as valid and reject any longer span; retain the existing default and cursor-only loading paths.
* Do NOT touch: curated-event windows, URL coordinate formatting, playback behavior, or data cache semantics.

### Commit 2 — enforce the cap at the API boundary

* Work in: `api/services/time.py`, `api/routes/{ercot_range,forecast,conditions}.py`, `api/tests/{test_ercot_range,test_forecast,test_conditions}.py`, and any focused helper test.
* Add a shared UTC-normalized range validator using `settings.max_state_range_hours`; reject reversed endpoints and spans beyond the configured limit with a consistent 422 detail before database work.
* Apply it to every explicit range request. Preserve `/forecast_range`'s omitted-bounds default-window behavior; reject partial `start`/`end` input rather than silently substituting a default bound.
* Add boundary tests for a valid 336-hour range and 422 cases for a 337-hour range, reversed endpoints, and forecast partial bounds. Assert rejection happens before queries are issued.
* Do NOT touch: response schemas, forecast horizon behavior, database query shapes, or the configured default limit.

## Acceptance

* [x] The picker rejects reversed and over-14-day custom windows without sending requests, and a direct oversized `ws`/`we` URL leaves the explorer in a clear error state without fetching.
* [x] Every explicit range endpoint returns 422 before database access for reversed, partial, or over-336-hour input; an exactly 336-hour range remains accepted.
* [x] Focused API tests and the web typecheck/lint pass.
