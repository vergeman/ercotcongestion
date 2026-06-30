# 0020 - zonal-clustering-sweep

Type: feat
Branch: feat/zonal-clustering

## Goal

* Ship `compute/experiments/zonal_clustering/run_clustering.py` — CLI sweep over (ref × algo × K) emitting one summary JSON + per-cell GeoJSON + per-cell ERCOT label CSV.
* Ship `compute/experiments/zonal_clustering/select_zones.py` — rank summary by `stab × sil × (1 - sc_model)`. No auto-pick.
* Skip-and-log empty `(0, 0)` matrices; never crash.

## Context

* 0017/0018/0019 ship algos, diagnostics, and polygons as pure functions. This sprint composes them.
* Input is the 0016 npz: per ref, `{ref}_{model,ercot}_C` plus aligned `bus_ids`/`sp_ids`/`hours`. One-sided refs land as `(0, 0)`.
* Coords: `data/processed/Texas2k_series25_case1_summerpeak_bus_coords.csv` (model) and `data/processed/settlement_points_geocoded.csv` (ERCOT).

## Approach

* `run_clustering.py::main()` — argparse CLI: `--matrices`, `--coords-model`, `--coords-ercot`, `--out-dir` (all required); `--ref-methods`, `--algos`, `--ks` (default `4,6,8,10,12,16`), `--seed` (0), `--alpha` (None → convex hull only; passed to `build_polygons` and `hybrid_geo`).
* Loader skips and logs `C.size == 0` cells; sweep loop only sees usable matrices.
* `ALGOS` registry maps name → function. `hybrid_geo` gets `coords` injected by the loop.
* Per cell: cluster → diagnostics (model) → polygons + GeoJSON → transfer to ERCOT SPs + label CSV → diagnostics (ERCOT, no stability). Exceptions become `status="failed"` rows, no crash.
* Emit `clustering_summary_<run_id>.json` (`run_id` = npz stem minus `congestion_matrices_`). Shape: `{run_id, generated_at, params, rows}`.
* `select_zones.py` — load summary, compute NaN-safe composite score, sort desc, print top N with `to_string()`.
* Tests: fabricate a 2-ref npz (one full, one ercot-empty) + matching coord CSVs in `tmp_path`; cover happy path, ercot-empty skip, failed-algo row, and `select_zones` smoke.
* Do NOT touch: `clustering.py`, `diagnostics.py`, `polygons.py`, the 0016 npz writer, or anything under `congestion_calculation/` and `preprocess/`.

## Status

Implemented. Smoke run on `congestion_matrices_test-persist.npz` (8 refs × 3 algos × 3 Ks): 63 ok, 9 skipped (`system_lambda` model-empty), 0 failed, ~25s. Full suite 29/29 green.

Two deviations from the plan:

* Two skip paths: empty matrices skipped at load time (no summary row), but per-cell skips for absent sides (e.g. `system_lambda` is ercot-only) do emit `status="skip"` rows so downstream can see which cells were intentionally not run.
* `cluster_stability_ari` reinjects `seed` itself, so the sweep strips its own `seed` from `a_kwargs` before forwarding to avoid a duplicate-keyword `TypeError`.

## Acceptance

* [x] CLI runs end-to-end on `congestion_matrices_test-persist.npz` without crashing.
* [ ] Full 5×6 grid sweep runs in < 10 min on the 0016 npz. *(not yet measured; 3×3 grid ran in ~25s)*
* [x] Every ok cell produces a GeoJSON, a label CSV (when ercot side exists), and a summary row.
* [x] Skipped cells log `SKIP …` and either omit the row (empty matrix) or record `status="skip"` (absent side).
* [x] Failed cells log `FAIL …` and emit a `status="failed"` row with no artifacts.
* [x] `pd.DataFrame(json.load(open(summary_path))["rows"])` loads with documented columns.
* [x] `select_zones --summary <path>` prints a ranked table; no writes.
* [x] `pytest compute/experiments/zonal_clustering/tests/test_run_clustering.py` passes (4/4).
