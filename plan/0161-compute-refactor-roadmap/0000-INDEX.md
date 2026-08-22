# 0161 - Compute refactor roadmap

Type: refactor
Branch: refactor/0161-compute-refactor-roadmap

## Goal

* Reduce coupling and duplicated conventions in `compute/` without changing forecast, map, or offline-backfill outputs.
* Sequence small, independently verifiable refactors from lowest to highest operational risk.

## Context

* `compute/` runs expensive offline calculations and production forecast jobs; correctness, causality, DST handling, memory bounds, and write ordering are contractual.
* This roadmap intentionally excludes algorithm, schema, model, and experiment-harness changes.
* Each subplan must preserve existing public function entry points until all in-repo callers and tests migrate.

## Order

1. [0001 Artifact paths](0001-run-artifact-paths.md) — establish a dependency-light shared convention.
2. [0002 Forecast store](0002-forecast-persistence-store.md) — remove job-to-job persistence ownership.
3. [0003 Shared operating defaults](0003-shared-operating-defaults.md) — eliminate duplicated production literals.
4. [0004 SF projection seams](0004-sf-projection-seams.md) — separate codec, sampling, map read, and orchestration.
5. [0005 Feature panel seams](0005-feature-panel-seams.md) — separate availability, source reads, and engineering.
6. [0006 Mu model seams](0006-mu-model-seams.md) — extract components from the walk/model monolith incrementally.
7. [0007 CT time helpers](0007-ct-time-helpers.md) — consolidate only after the preceding work and with explicit DST coverage.

## Acceptance

* [ ] Each completed subplan preserves calculation outputs and database write semantics.
* [ ] Each completed subplan passes its focused test suite before the next begins.
* [ ] No subplan changes frozen experiment behavior or adds a second model/persistence implementation.

