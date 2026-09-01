# 0194 - analysis-panel service boundaries

Type: refactor
Branch: refactor/0194-analysis-panel-services

## Goal

* Replace the 1,966-line `api/services/analysis/panels.py` integration module with focused, route-independent Analysis services.
* Preserve every `/analysis/*` URL, request parameter, response model, unavailable reason, Brief payload, and settled/forecast ranking rule.
* Fix the stale `render()` and `_BRIEF_SOURCE_DEFINITIONS` references while establishing their owning modules.

## Context

* `panels.py` currently owns FastAPI parameter declarations, connection checkout, SQL, artifact reads, pandas projections, ranking/comparison policy, Pydantic assembly, and the callable surface used by `brief.py`.
* `get_standouts()` alone combines constraint and node standouts, histories, geography, ESSP grouping, ranking, percentile assembly, and response construction; the surrounding helpers repeat the same forecast-versus-settled concepts.
* The focused route package already exists, but its routers register `panels.get_*` directly and `brief.py` composes those endpoint-shaped functions in a thread pool.
* `get_hero()` calls `render(slots)` without importing `compute.analysis.phrases.render`; `get_grade_history()` references undefined `_BRIEF_SOURCE_DEFINITIONS` instead of `brief_grade.SOURCE_DEFINITIONS`.

## Organization

```text
api/services/analysis/
  selection.py                  # existing resolution policy and AnalysisSelection
  repositories/
    market.py                    # DAM SPP/lambda, landed status, settled congestion
    geography.py                 # constraint geography
    histories.py                 # 30-day constraint/node forecast and settled series
    essp.py                      # hourly ESSP membership and delivery-day canonical groups
    grades.py                    # materialized grade rows
  policy/
    rankings.py                  # joined top-k, rank maps, history percentile helpers
    standouts.py                 # eligibility and forecast/settled standout selection
  features/
    hero.py                      # hero build, verdict, cursor, latest-day lookup
    catalog.py                   # node detail, settlement-point, constraint, ESSP catalog
    grades.py                    # grade and grade history
    constraints.py               # top constraints and structural context
    nodes.py                     # top nodes
    standouts.py                 # constraint and node standout orchestration
  facade.py                      # temporary stable callable exports for Brief/route migration
```

Keep `api.services.sf_artifacts` as the owner of artifact decoding/cache and `compute.analysis.brief_grade` as the owner of grade profile construction and source definitions. Do not introduce a second artifact cache or domain-schema layer.

## Approach

### Commit 1 — repair the current execution paths and establish tests

* Work in: `api/services/analysis/panels.py`, `api/tests/test_analysis.py`.
* Import `render` from `compute.analysis.phrases` for hero segment assembly.
* Replace all `_BRIEF_SOURCE_DEFINITIONS` uses in grade-history assembly with `brief_grade.SOURCE_DEFINITIONS`; retain the existing serialized descriptor shape and source ordering.
* Add direct tests that execute the hero rendering path and grade-history descriptor construction, so undefined globals/imports cannot be masked by Brief handler monkeypatches.
* Do NOT change response fields, grade source IDs, or hero prose in this commit.

### Commit 2 — extract shared read concerns and pure policy

* Work in: `api/services/analysis/selection.py`, new `repositories/` and `policy/` modules, `api/services/analysis/panels.py`, focused unit tests.
* Promote the existing `ArtifactSelection` into the normalized selection passed after the HTTP boundary resolves run/day/horizon; keep existing `resolve_*`, CT-day, 422, 503, and artifact-missing behavior intact.
* Move raw SQL/result normalization into narrow repositories: market state/congestion, constraint geography, ESSP grouping, histories, and materialized grade reads. Repositories accept a cursor and return plain values/DataFrames; they do not import FastAPI schemas or routes.
* Move pure `_joined_top_keys`, percentile/history-stat construction, standout eligibility/ranking, and ESSP canonicalization into policy modules. Cover forecast-only and settled ranking, quiet days, tie stability, and group collapse with DataFrame/value tests.
* Keep `load_daily_artifact`, `load_daily_artifacts`, and `load_realized_mu` delegated to `api.services.sf_artifacts`; keep grade profiles delegated to `brief_grade`.

### Commit 3 — split feature services, starting with standouts

* Work in: new `features/` modules, `api/services/analysis/queries.py`, `api/services/analysis/panels.py`, `api/tests/test_analysis.py`.
* Extract standalone services for hero, catalog/node detail, grades, constraints/context, top nodes, and standouts. Each takes plain arguments plus explicit repository/artifact collaborators and returns the existing Pydantic response type.
* Split constraint and node standout assembly within `features/standouts.py` into separately testable functions; share only history/ranking/ESSP policy, not a single multi-purpose function.
* Move response assembly beside its feature service. Remove callback injection from `queries.node_response`; make node-detail dependencies explicit through its service/repository collaborators.
* Preserve the present availability behavior: resolve before artifact read, distinguish missing artifact from settlement pending, and keep forecast fallback whenever DAM is absent.
* Do NOT change SQL semantics, `k` bounds, history windows, market-peak CT hours, response ranking, or Brief cache behavior.

### Commit 4 — make routes and Brief consume service APIs

* Work in: `api/routes/analysis/`, `api/services/analysis/brief.py`, new `api/services/analysis/facade.py`, `api/tests/test_analysis.py`, `api/tests/test_openapi.py`.
* Make each route module own its FastAPI `Query`/`Depends` declaration and delegate to the relevant feature service after constructing/resolving selection. Feature modules must not import FastAPI route functions or route modules.
* Change `brief.py` to compose explicit feature service calls rather than `panels.get_*`; retain its one-time run/horizon selection, connection-pool budget, section timing logs, cache keys, progressive shell/stats/details endpoints, and parallelism.
* Provide a temporary facade with the current callable names while direct callers migrate. Move tests away from patching `panels` internals toward service collaborators and policy functions; retain thin route contract/OpenAPI tests.
* Do NOT change public URLs, query names, OpenAPI response unions, cache capacities, or the Brief wire format.

### Commit 5 — remove the transitional monolith

* Work in: `api/services/analysis/panels.py`, imports/callers, tests.
* Delete `panels.py` after all production callers use route handlers, feature services, or the narrowly named facade. If a compatibility re-export remains necessary, it must contain imports only and no SQL/pandas/HTTP logic.
* Remove obsolete helper aliases and callback plumbing, then run import-cycle checks.
* Update `api/ROUTE_INVENTORY.md` only if module ownership is documented there; do not alter client contracts or compute modules.

## Acceptance

* [ ] `render` is imported from `compute.analysis.phrases`, and both hero and grade-history paths execute without a `NameError`.
* [ ] Grade-history source descriptors come exclusively from `brief_grade.SOURCE_DEFINITIONS` and retain the current IDs, labels, definitions, and ordering.
* [ ] Route modules contain HTTP binding/input normalization plus one service call; feature services do not use `Query`, `Depends`, or import an Analysis route module.
* [ ] SQL and cursor normalization live in focused repositories; pandas calculations and comparison policy live in feature/policy modules, not route handlers or a monolithic facade.
* [ ] Constraint and node standouts are independently testable, while their public `Standouts*` response remains byte-for-byte contract-compatible.
* [ ] Brief composition calls feature services directly and preserves its selection consistency, parallel section loading, caches, slow-request logs, and payload shape.
* [ ] `/analysis/*` OpenAPI paths, parameter names/defaults/bounds, response unions, status behavior, ranking, CT-day handling, and unavailable reasons are unchanged.
* [ ] Focused policy/service tests plus `api/tests/test_analysis.py` and `api/tests/test_openapi.py` pass in the project API test environment.
