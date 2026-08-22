# 0161-0005 - Separate feature-panel seams

Type: refactor
Branch: refactor/0161-compute-refactor-roadmap

## Goal

* Isolate availability rules, source loading, and pure feature engineering around the μ panel.
* Preserve the one-pass, memory-aware `build_panel` behavior.

## Context

* `compute/mu/features.py` combines CT/DAM-vintage rules, SQL, source readers, refit features, and panel assembly.
* The feature panel is leakage-sensitive and is among the most expensive computations in this directory.

## Approach

* Work in: `compute/mu/features.py` and new `compute/mu/` modules as needed.
* First extract pure availability/time functions, then source-reader functions, then pure transformations; keep `build_panel` as the orchestrating public façade.
* Preserve query boundaries, indexes, dtypes, column names, joins, and build order.
* Add or retain direct tests for DAM-close cutoffs, DST bounds, vintage SQL parameters, candidate keys, and `audit_leakage`.
* Do NOT rebuild the panel per feature family or change the historic/serveable cutoff model.

## Acceptance

* [ ] Existing feature tests pass unchanged.
* [ ] Representative panels have identical index, columns, dtypes, and values.
* [ ] A fixed input still yields the same leakage audit result.

## Suggested regression tests

* Use the existing in-memory/source fakes to build one representative panel before and after each extraction, then assert `assert_frame_equal(..., check_dtype=True, check_exact=True)` including index names and column order.
* Add parameterized DAM-close tests around ordinary, spring-forward, and fall-back delivery days; assert every source query receives the same inclusive/exclusive timestamps and vintage cutoff as the current implementation.
* Retain a deliberately leaked fixture and a legal fixture for `audit_leakage`; assert both produce the same pass/fail diagnostics after the module split.
