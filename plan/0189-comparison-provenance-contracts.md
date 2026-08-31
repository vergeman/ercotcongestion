# 0189 - comparison-provenance-contracts

Type: refactor
Branch: refactor/0189-comparison-provenance-contracts

## Goal

* Replace overloaded comparison values with self-describing, domain-owned IDs in compute, Scoreboard, and Brief data.
* Migrate persisted Scoreboard source values without changing grading formulas or metric values.
* Expose comparison descriptors through a backward-compatible API contract.

## Context

* This plan follows 0188, which removes inactive μ comparisons and establishes the metric boundary.
* Short values such as `model` and `persistence` currently describe materially different weekly, served, and Brief constructions.
* The stored `source` value is part of Scoreboard primary keys, so migration must preserve counts and uniqueness exactly.

## Canonical naming contract

Use lowercase snake case: `<owner>_<method>_<descriptor...>`. The owner is mandatory.

| Owner | Canonical IDs |
| --- | --- |
| Compute μ evaluation | `compute_mu_model_walk_forward`, `compute_mu_persistence_prior_day`, `compute_mu_climatology_hourly`, `compute_mu_oracle_realized`, `compute_mu_null_zero` |
| Weekly Scoreboard | `scoreboard_model_backtest_nodal`, `scoreboard_persistence_backtest_nodal`, `scoreboard_climatology_backtest_nodal`, `scoreboard_oracle_backtest_nodal`, `scoreboard_null_flat_nodal` |
| Served Scoreboard | `scoreboard_model_served_nodal`, `scoreboard_persistence_prior_day_nodal`, `scoreboard_climatology_trailing_window_nodal`, `scoreboard_oracle_settled_mu_nodal`, `scoreboard_null_flat_nodal` |
| Brief | `brief_model_artifact_profile`, `brief_persistence_prior_settled_profile`, `brief_climatology_trailing_settled_profile` |

`scoreboard_null_flat_nodal` is shared because its construction is identical in both cadences. All other Scoreboard IDs encode their distinct construction.

## Approach

* Work in: `compute/evaluation/mu.py`, `compute/jobs/backfill_scoreboard.py`, `compute/jobs/grade_forecast_day.py`, Brief-grade code, `db/migrations/`, Scoreboard/analysis API schemas and services, and focused tests.
* Add local typed comparison-definition tables in each owning domain. Definitions carry `id`, `series_id` where charted, `label`, `definition`, and existing construction key/callable. Do not create a global cross-domain source enum or relocate code.
* Make compute evaluation write the five admitted `compute_mu_*` IDs. Map them explicitly in `backfill_scoreboard` to weekly `scoreboard_*` IDs and reject unknown values.
* Make served daily grading write served `scoreboard_*` IDs directly. Convert Brief serialization to named `brief_*` comparison records; do not imply a Brief profile is a nodal Scoreboard source.
* Add a lossless migration from short Scoreboard source values to canonical IDs. Preserve all rows, metric values, horizons, and primary-key uniqueness; do not add a parallel source column.
* Add `ComparisonDescriptor { id, series_id, label, definition }` to API responses. Use canonical IDs in headline/persistence logic rather than literal `"model"` lookups.
* Ship descriptors alongside bounded legacy fields for one frontend deployment. Record the compatibility retirement in 0190; do not silently change existing response strings.

## Commit groups

1. `refactor(compute): name evaluation comparisons` — local definitions, canonical compute IDs, and tests.
2. `refactor(scoreboard): canonicalize persisted comparisons` — source mapping, served-grade IDs, migrations, and verification.
3. `refactor(api): expose comparison provenance` — Scoreboard/Brief descriptors, compatibility fields, and API tests.

## Acceptance

* [x] Every persisted comparison has a canonical owner-qualified ID and a tested construction definition.
* [x] `backfill_scoreboard` admits only the five compute IDs and maps each to its weekly Scoreboard identity.
* [x] Existing Scoreboard rows migrate losslessly and preserve keys, counts, horizons, and metric values.
* [x] Brief API data uses only `brief_*` identities.
* [x] API responses include descriptors and retain bounded compatibility fields until 0190 completes.
* [x] Focused compute, migration, and API suites pass.

## Verification notes

* The focused compute provenance suites passed (36 tests) and the full API suite passed (152 tests, 3 skipped).
* Migration 48 was verified in a rolled-back transaction against the dev database: 230 weekly and 120 daily admitted rows retained their counts while receiving canonical IDs.
* The migration rejects retired or unknown source values (including stale `model_clim`) instead of silently deleting or mislabeling them. Remove those rows as the prerequisite cleanup from 0188 before applying 48 to a database that still contains them.
