# 0191 - remove-unconsumed-analysis-routes

Type: chore
Branch: chore/0191-remove-unconsumed-analysis-routes

## Goal

* Remove four standalone `/analysis` routes whose only consumer is the in-process `/brief` bundle: `/context`, `/top-nodes`, `/top-constraints`, `/grade-history`.
* Fully remove `/analysis/forecast-mu` — no HTTP or in-process consumer at all.
* Keep the panel handlers for the first four; the `/brief` bundle calls them directly.

## Context

* Frontend HTTP calls only reach 12 of the 18 `/analysis` routes (verified against `web/src/api/`).
* `/brief` composes `context`, `top_nodes`, `top_constraints`, `grade_history` in-process via `panels.get_*` (`api/services/analysis/brief.py:116-120`), so those standalone routes are redundant à-la-carte access.
* `/forecast-mu` is called by nothing but its own test; `plan/0139-.../0003-detail-pane.md` already calls it "unused".
* `/grade` and `/standouts` stay — the frontend calls both directly.
* All five live only under the `/analysis` prefix (no root-mount/compat duplicate).

## Approach

* Work in: `api/routes/analysis/`, `api/schemas/analysis.py`, `api/services/analysis/panels.py`, `api/tests/`, `api/ROUTE_INVENTORY.md`.
* Route-only deletions (keep the handler + schema):
  * `insights.py:15` `/context`
  * `insights.py:21` `/top-nodes`
  * `insights.py:12` `/top-constraints`
  * `grading.py:14` `/grade-history`
* Full deletion of `/forecast-mu`: route `catalog.py:26`, handler `panels.get_forecast_mu`, schema at `api/schemas/analysis.py:190`, and any query used only by it.
* Update tests: drop the five paths from the `public_routes` tuple in `test_openapi.py:80-87`; delete the standalone-route tests in `test_analysis.py` for `/grade-history`, `/forecast-mu`, `/top-constraints`, and any for `/context`/`/top-nodes`.
* Update `ROUTE_INVENTORY.md:21-22` to drop the removed routes.
* Split into two commits: (1) the four route-only deletions, (2) the `/forecast-mu` full removal.
* Do NOT touch: `/grade`, `/standouts`, any `panels.get_*` handler still used by `/brief`.

## Acceptance

* [x] `GET /analysis/{context,top-nodes,top-constraints,grade-history,forecast-mu}` return 404. — routes absent from the OpenAPI schema (`test_openapi` passes; the five paths dropped from `public_routes`).
* [x] `GET /analysis/brief` response is unchanged (all sections still populated). — brief/details tests pass; `context`, `top_nodes`, `top_constraints`, `grade_history` still composed in-process via `panels.get_*`.
* [x] `panels.get_forecast_mu` and its schema no longer exist; the other four handlers remain. — handler, `forecast_mu_response`, the three `ForecastMu*` schemas, and the `compute/analysis/forecast_mu.py` module + test all removed.
* [x] `api/tests` pass; no reference to the removed routes remains in tests or `ROUTE_INVENTORY.md`. — `api/tests` + `compute/analysis/tests`: 185 passed, 3 skipped (the 2 `test_hero_*` failures pre-date this branch and are unrelated).

## Note

Before merge, confirm no external public caller hits these `/analysis` endpoints (`ROUTE_INVENTORY.md:7` flags this and asks to remove at a version boundary). If traffic can't be verified, gate on the deprecation window.
