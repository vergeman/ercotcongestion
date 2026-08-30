# 0002 - Analysis query services

Type: refactor
Branch: refactor/0181-analysis-query-services

## Goal

* Extract Analysis query, resolution, artifact, and profile policies from the router.
* Give Analysis use cases callable services that do not import FastAPI route functions.

## Context

* `api/analysis.py` is 1,944 lines with 13 endpoint handlers and extensive shared pandas/SQL helpers.
* Node, constraint, insight, grade, and hero handlers share run/horizon and artifact behavior but currently own it beside decorators.
* Brief composition still needs these services, so this extraction precedes splitting the Brief routes.

## Approach

* Work in: `api/analysis.py`, `api/services/analysis/`, `api/schemas/analysis.py`, and `api/tests/test_analysis.py`.
* Entry point / primary change: create cohesive services rather than one module per current private helper.
* Add a resolution service for selected run, delivery-day, horizon, artifact availability, and selected-hour rules; preserve current 503/unavailable behavior.
* Add profile/query services for realized and forecast μ/node histories, contribution terms, constraint geography, and grade inputs. Pass cursors, artifacts, and collaborators explicitly where it prevents router coupling.
* Move endpoint-specific assembly into named service functions for node, settlement-point, constraints, ESSP, forecast-μ, context, standouts, top-constraints, top-nodes, grade, and grade-history.
* Leave the existing router and URL decorators in place for this branch; handlers should delegate to services and retain request parsing/HTTP exception translation.
* Do NOT touch: Brief bundle composition, cache sizes/keys, SQL result semantics, or public Analysis URLs.

## Acceptance

* [x] Analysis services can be called without importing `api.analysis` or a decorated handler.
* [ ] `api/analysis.py` no longer contains shared profile/history/ranking query policy.
* [ ] Existing Analysis unit tests pass unchanged or move only their import target to a service boundary.
* [ ] Availability, selected run/horizon, CT-day, and response-model behavior remain unchanged.

Validation: `docker compose run --rm --no-deps api pytest -q tests/test_analysis.py` — 50 passed, 3 existing failures (Grade fixture sequencing and Top Constraints response expectation mismatch).
