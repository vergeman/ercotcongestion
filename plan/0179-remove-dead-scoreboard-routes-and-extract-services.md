# 0179 - remove dead scoreboard routes and extract services

Type: refactor
Branch: refactor/0179-remove-dead-scoreboard-routes-and-extract-services

## Goal

* Retire the unused primitive Scoreboard HTTP routes and their selector-era contract.
* Keep `/scoreboard/summary` as the sole Scoreboard read endpoint.
* Move Scoreboard data assembly and query concerns out of `api/scoreboard.py` into services.

## Context

* The web client consolidated its Scoreboard fetches to `/scoreboard/summary`; the route inventory found no in-repository consumers of `/scoreboard/headline`, `/scoreboard/weekly`, or `/scoreboard/daily`.
* The live panel now needs only the latest final (h1) grade; date, horizon, `since`, and run-selection request controls were dead compatibility behavior.
* `api/scoreboard.py` still owns weekly pooling, live-grade selection, history assembly, and summary orchestration alongside its router declaration; `services/scoreboard_headline.py` already establishes a service boundary for related work.

## Approach

* Work in: `api/scoreboard.py`, `api/services/scoreboard*.py`, `api/main.py`, `api/models.py`, `api/schemas/scoreboard.py`, `api/tests/test_scoreboard_*.py`, `api/tests/test_openapi.py`, `api/ROUTE_INVENTORY.md`, and `web/src/api/types.ts`.
* Completed route-removal change: delete the three primitive route decorators and public request parameters; retain only `/scoreboard/summary` and its latest-final h1 daily section.
* Completed contract cleanup: remove `ScoreboardDaily.since` and `ScoreboardDaily.horizons`; make `selected_delivery_date` required and retain `horizon=1` as final-forecast provenance.
* Extract the remaining query/build concerns from `api/scoreboard.py` into a cohesive `services/scoreboard.py` module (or a small, clearly named set of scoreboard service modules): weekly run resolution and pooling, latest-final daily selection, and composed score-history construction.
* Move summary orchestration to the service boundary where it can reuse the existing bootstrap availability helpers; leave `api/scoreboard.py` as a thin router that delegates to the service.
* Decide whether to fold `services/scoreboard_headline.py` into the new service module only after auditing its Map-bootstrap consumer; preserve `map.py`'s headline behavior and avoid duplicating run-resolution logic.
* Update unit tests to import/test service builders directly and keep one OpenAPI assertion that the three retired paths are absent.
* Do NOT touch: `scoreboard_daily.horizon`, preview forecast/grading jobs, persisted preview rows, or the Map headline response contract.

## Acceptance

* [x] `/scoreboard/headline`, `/scoreboard/weekly`, and `/scoreboard/daily` are absent from OpenAPI and the route inventory; `/scoreboard/summary` remains available.
* [x] The summary's daily payload contains only the newest h1 comparator rows and no selector-era `since` or `horizons` fields.
* [x] `api/scoreboard.py` contains only router registration and a thin summary handler; no SQL, pooling, date-selection, or history-building helpers remain there.
* [x] Scoreboard service builders preserve independent weekly/daily run provenance, 503-to-unavailable summary behavior, and Map's headline behavior.
* [x] Focused scoreboard service/summary/OpenAPI tests pass, including latest-final selection and absence of the retired paths.
