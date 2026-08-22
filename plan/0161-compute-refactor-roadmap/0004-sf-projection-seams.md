# 0161-0004 - Separate SF projection responsibilities

Type: refactor
Branch: refactor/0161-compute-refactor-roadmap/0004-sf-projection-seams

## Goal

* Separate projection serialization, sampling, persisted-map reads, and window orchestration.
* Keep `propagate_window` as the stable shared integration API.

## Context

* `compute/sf/project.py` currently contains NPZ codecs, Monte Carlo draws, metrics, map DB reads, and forward/backtest propagation.
* Both offline backfill and live daily forecast depend on identical draw and artifact semantics.

## Approach

* Work in: `compute/sf/project.py` and new narrowly scoped `compute/sf/` modules.
* Extract codecs (`NodalPanel`, `SfMuArtifact`, save/load functions), sampling (`residual_pool`, draw and band calculations), and map-store reads/guards in separate extract-only commits.
* Leave `propagate_window` as a façade that imports these components; preserve public re-exports from `project.py` during migration.
* Use deterministic RNG fixtures and serialized-artifact fixtures to compare results before and after each extraction.
* Do NOT change draw count, RNG ordering, percentile dtypes, map freshness/coverage guards, or SQL.

## Commit groups

* [x] Extract NPZ codecs and artifact read helpers into `compute/sf/codecs.py` while re-exporting them from `project.py`.
* [x] Extract fixed-seed draws and band metrics into `compute/sf/sampling.py` while preserving the façade API.
* [x] Extract persisted-map reads and guards into `compute/sf/map_store.py` and test its failure contracts at the new seam.

## Acceptance

* [x] Fixed-seed draws, band metrics, and NPZ round trips are unchanged.
* [x] Forward and historical propagation tests pass without changed expected values.
* [x] `daily_forecast` and `backfill_nodal` still import a stable propagation API.

## Suggested regression tests

* Build a compact fixed fixture (`SF`, weekly predictions, residual pool, hours) and compare pre/post extraction draw arrays with `np.array_equal`, not only approximate metrics; assert matching p10/p50/p90, point panel, and dtype.
* Serialize the same `NodalPanel` and `SfMuArtifact` before/after each codec extraction; compare NPZ member names, decoded frames, and artifact bytes where NumPy serialization remains deterministic.
* Cover both `propagate_window` modes with the same seed: historical mode must retain its metric row; forward mode must retain `row is None`, CT/DST hour counts, and never read future realized congestion.
* Mock map-store reads to prove missing, stale, empty, and low-coverage maps raise the same failure class/message contract and produce no downstream write.
