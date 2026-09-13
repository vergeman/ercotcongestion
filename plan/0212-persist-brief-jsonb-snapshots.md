# 0212 - Persist Brief JSONB snapshots

Type: feat
Branch: feat/0212-persist-brief-jsonb-snapshots

## Goal

* Persist final Brief panel payloads by run, delivery day, and horizon.
* Serve settled history without per-pod in-memory Brief caches or cold recomposition after deployment.

## Context

* The root Brief makes separate hero, details, and standouts requests; their `OrderedDict` caches are lost on every pod/container deployment.
* A settled h1 Brief is immutable and normally computed once, while deploys are more frequent than Brief-data changes.
* A representative complete day is about 113 KB JSON (22 KB gzip), making durable JSONB snapshots modest storage.

## Approach

* Work in: `db/migrations/50_brief_daily_snapshot.sql`, `api/services/analysis/brief.py`, `api/services/analysis/panels/standouts.py`, `compute/jobs/daily_forecast.py`, and `api/tests/test_analysis.py`.
* Add `brief_daily_snapshot`, keyed by `(run_id, delivery_date, horizon)`, with separate `hero`, `details`, and `standouts` JSONB columns, `computed_at`, and `schema_version`.
* For final settled h1 requests, read the matching snapshot first; on a miss, compose the requested payload, insert it with `ON CONFLICT DO NOTHING`, then return the stored row. Keep current/future/unsettled and preview requests live.
* Materialize all final panel columns together in the daily settlement flow (or a dedicated idempotent backfill) so first-paint hero never causes a later details cold start.
* Remove `_BRIEF_CACHE`, `_BRIEF_HERO_CACHE`, `_BRIEF_DETAILS_CACHE`, their lock, and cache-reset test setup. Retain the browser’s five-minute request dedupe cache.
* Use an explicit snapshot schema version and an idempotent rebuild/backfill path for intentional response-shape or calculation changes.
* Do NOT touch: the Brief API response contracts, live non-final behavior, or replace SQL query tables with a PostgreSQL materialized view.

## Acceptance

* [ ] A final settled Brief reads identical hero/details/standouts JSONB after an API restart, without recomposing panels.
* [ ] A snapshot miss produces one durable row; concurrent requests converge on the stored payload.
* [ ] Non-final or non-h1 Briefs still compose live and create no snapshot.
* [ ] Tests cover cache removal, snapshot hit/miss, finality gating, and idempotent write behavior.
