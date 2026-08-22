# 0161-0007 - Consolidate CT delivery-time helpers

Type: refactor
Branch: refactor/0161-compute-refactor-roadmap

## Goal

* Establish one tested implementation of CT delivery-day normalization and bounds.
* Preserve all existing DST and legacy-row replacement semantics.

## Context

* CT conversion logic is repeated across daily forecasting, grading, and nodal backfill.
* This duplication is small, but a mistaken consolidation could cause a silent DST or UTC-label regression.

## Approach

* Work in: new `compute/time.py`, `compute/mu/features.py`, and consumers in `compute/jobs/`.
* Define narrowly named primitives for CT delivery bounds, CT-day normalization, and delivery-date bucketing; migrate one consumer at a time.
* Retain local wrapper functions where tests or callers patch them until migration is complete.
* Add table-driven tests for ordinary days and spring-forward/fall-back days, including UTC seam hours and both horizons.
* Do NOT alter stored timestamp format, CT delivery-date labels, DAM-close cutoff policy, or delete-by-UTC-window behavior.

## Acceptance

* [ ] All existing CT boundary, forecast-day, grade-day, and nodal-write tests pass.
* [ ] New DST table tests prove 23-, 24-, and 25-hour blocks and correct CT labels.
* [ ] Reprocessing a legacy UTC-labeled day still deletes/replaces by the exact timestamp window.

## Suggested regression tests

* Table-test CT dates spanning standard time, daylight time, spring-forward, and fall-back; assert normalized UTC start/end instants, block lengths, local delivery labels, and the final timestamp in each block.
* Feed UTC seam-hour timestamps into the shared bucketing helper and assert they match the current backfill labels rather than UTC calendar dates.
* With a recording DB fake, republish spring-forward and fall-back days containing legacy labels; assert the delete predicate uses the exact CT-derived UTC interval and never reaches an adjacent delivery block.
