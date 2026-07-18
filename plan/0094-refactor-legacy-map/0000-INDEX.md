# 0094 - refactor: remove the legacy zonal/clustering map

Teardown of the pre-v3 map product: the clustering/scorecard "cells", the
`served_run_dir` / `current` symlink serving model, `compute.promote`, `/api/meta`,
and the frozen `compute/legacy/` compute (clustering, mapping, matrix, …).

The current product is **SF map + Congestion + LMP**. What stays:

* `/map/*` (SF) — `api/map.py`, `compute/sf`, `compute/mu`.
* `/ercot_spp_range` (**LMP**) — already DB-backed (`ercot_dam_spp`), no legacy dep.
* `/topology` — geocoded SP GeoJSON; does not read `served_run_dir`.

## The blocker (read first)

`/ercot_state_range` (**Congestion** = `SPP − system_λ`) is the *only* remaining
reader of `served_run_dir` besides `/api/meta`, and it reads two **legacy artifacts**:
`served_run_dir/matrix/congestion_matrices.npz` and `mapping/scorecard.json` (for
`params.ref`). Both are produced only by `compute/legacy/`. So Congestion must be
**re-sourced off the legacy artifacts before** `served_run_dir` / `matrix` / `mapping`
can be deleted. That is `0002`, and it gates `0003`/`0004`.

The natural re-source: compute `SPP − system_λ` from the DB at request time, exactly
as `compute/sf/panels.load_congestion_panel` already does (and as `/ercot_spp_range`
reads SPP). Recommended; confirm before executing `0002`.

## Order

1. `0001-remove-api-meta` — delete `/api/meta` + `MetaResponse` (web does NOT call it
   — the earlier "web uses /meta" was a `/map/meta` substring false positive). Independent.
2. `0002-resource-congestion` — re-source `/ercot_state_range` from the DB; drop its
   `served_run_dir` / matrix / scorecard reads. **The gate.**
3. `0003-remove-promote-and-served-run` — delete `compute/promote.py`, the
   `served_run_dir` setting + `current` symlink model, scorecard-cell serving, and the
   ops wiring (`SERVED_RUN_DIR`, the promote shell pod). After 0001+0002 nothing reads
   `served_run_dir`.
4. `0004-delete-legacy-compute` — delete `compute/legacy/` (clustering, mapping,
   matrix, calibration, regimes, snapshot, run_pipeline, …) and its tests/docs. After
   0002/0003 nothing produces or consumes its artifacts.

## Relationship to 0093

Sequence 0094 **after** 0093 (bp already gone). `0093-0001` decouples `/api/meta` from
the bp pointer; `0094-0001` then removes `/api/meta` entirely — if 0094 lands first the
bp-table drop (`0093-0004`) still just needs the meta bp-read gone, which 0094-0001
also delivers.

## Numbering note

The incremental-append doc (`0093-0005`) referenced a future `0094-refactor-model`;
that model refactor is renumbered to **`0095-refactor-model`** so `0094` is this
legacy-map removal, per direction.
