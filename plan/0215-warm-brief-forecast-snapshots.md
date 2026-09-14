# 0215 - Warm Brief forecast snapshots

Type: feat
Branch: feat/0215-warm-brief-forecast-snapshots

## Goal

* Persist Brief payloads for newly published T+2 and T+1 forecast vintages as well as settled T+1 history.
* Warm the matching Brief snapshot after each successful forecast publish, while retaining cache-aside composition when a job did not create one.
* Replace a provisional snapshot only at an explicit later publish/settlement stage, never merely because a reader requested it.

## Context

* `brief_daily_snapshot` is keyed by `(run_id, delivery_date, horizon)`, but migration 50 constrains it to horizon 1.
* The Brief service currently reads/writes a snapshot only when an h1 day is past in CT and DAM has landed; front days therefore compose live except for the browser's five-minute cache.
* `daily_forecast.persist_forecast` commits the forecast artifact and served pointer atomically before its post-publish grade/materialization work begins.

## Approach

### Commit 1 — Make Brief snapshots multi-horizon, versioned forecast-vintage cache entries

* Work in: `db/migrations/`, `api/services/analysis/brief.py`, and `api/tests/test_analysis.py`.
* Add forward migration `52_warm_brief_forecast_snapshots.sql` to replace the horizon-1 check with `horizon IN (1, 2)`; preserve the existing primary key `(run_id, delivery_date, horizon)` and existing rows.
* Add an explicit snapshot state/provenance column (preview, forecast, settled) with a valid-state constraint and a migration-safe default for existing historical h1 rows.
* Split snapshot lookup from finality gating. All resolved Brief requests must check the keyed snapshot first, regardless of horizon or delivery-date position.
* On a miss, compose the complete hero/details/standouts payload and insert it as a cache-aside entry. Concurrent readers must converge on the stored row rather than return divergent payloads.
* Add a job-only replacement path that atomically overwrites the payload, state, schema version, and timestamp for the same key. Keep normal request writes insert-only so a read cannot unexpectedly replace a published vintage.
* Derive snapshot state from the artifact horizon and settlement completeness: h2 is `preview`; unsettled h1 is `forecast`; a past h1 with DAM landed is `settled`. Retain schema-version invalidation for deliberate response-shape/calculation changes.
* Keep run/horizon resolution unchanged: normal Brief requests continue to select h1 when available and h2 only when h1 is absent.
* Do NOT change Brief HTTP response shapes, query parameters, the browser request-cache TTL, or the artifact horizon-selection policy.

### Commit 2 — Materialize each published forecast and refresh settlement

* Work in: `compute/jobs/materialize_brief_snapshot.py`, `compute/jobs/daily_forecast.py`, `compute/analysis/tests/test_brief_grade.py`, and focused job tests.
* Generalize the materializer from final-h1-only to an internal `materialize_snapshot(..., replace=True)` operation that can write h2 preview, h1 forecast, and h1 settled states through the same Brief composition service.
* Call it after `persist_forecast()` returns for both h1 and h2, so the forecast transaction and pointer have committed before the Brief reader can resolve the new artifact.
* Retain/extend the existing post-grade h1 materialization to replace that delivery day's forecast snapshot after the day is past and DAM/grade data is available.
* Treat all prewarm/refresh failures as non-fatal after forecast publication: log the run, delivery date, horizon, and target state; let the first Brief request use cache-aside composition and insertion.
* Ensure a same-run re-publish deliberately replaces the matching snapshot, while h1 publication never alters the separately keyed h2 preview snapshot.
* Do NOT make forecast publication wait for a successful Brief materialization before committing its artifact/pointer, and do not call the public HTTP API from a compute job.

### Commit 3 — Cover staged-cache and fallback contracts

* Work in: `api/tests/test_analysis.py`, `compute/analysis/tests/test_brief_grade.py`, and any directly affected fixtures.
* Test h2 and unsettled h1 snapshot hits bypass section composition; test a missing front-day snapshot composes once and becomes the next request's cache hit.
* Test default selection serves h2 when it is the only artifact/snapshot and h1 once h1 exists, with no key collision between horizons.
* Test job materialization writes after publish for both horizons, the settled h1 refresh replaces its prior forecast payload/state, and a materialization exception does not roll back a published forecast.
* Test ordinary request-side cache-aside writes cannot overwrite a job-published snapshot; test a schema-version bump remains an intentional replacement path.
* Add migration assertions covering valid h1/h2 rows, rejection of other horizons/states, and preservation of existing settled h1 data.

## Acceptance

* [x] `brief_daily_snapshot` accepts and keys both h1 and h2 snapshots without changing the run/day/horizon identity.
* [x] A successful T+2 or T+1 forecast job precomputes the corresponding Brief payload after its forecast data commits.
* [x] A normal Brief request reads a warm front-day snapshot; a missing snapshot composes the identical payload and stores it for later requests.
* [x] H1 automatically supersedes h2 for ordinary Brief resolution while their independently keyed snapshots remain intact.
* [x] The post-settlement h1 job refresh replaces the provisional h1 payload with its settled/graded payload.
* [x] A Brief prewarm failure is logged but cannot undo or make unavailable a successfully published forecast.
* [x] Focused API and compute tests cover multi-horizon storage, cache-aside fallback, replacement stages, selection precedence, and failure isolation.
