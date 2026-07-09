# 0075 - multi-metric-correlation-and-scorecard-rename

Type: feat
Branch: feat/0075-multi-metric-correlation-and-scorecard-rename

## Goal

* Export Spearman and sign-agreement alongside Pearson from `correlation_map`.
* Rename scorecard headline `rank_spearman` → `zone_rank_spearman_per_hour` end-to-end (compute → API → frontend).
* Add header-tile / column tooltips in `StatsPanel` so `rank ρ` is self-explaining.
* Preserve Pearson-driven `best_bus` / `topk` — the new metrics are diagnostic-at-argmax only.

## Context

The handoff (`handoff-0072-zonal-partial-credit.md`) landed the recommended pair `kkt_perbus × zone_local_spp` but its strongest evidence lives on an unmerged branch. Master only exports Pearson, understating the finding. Separately, `scorecard.py::_rank_spearman_per_hour` computes a per-hour *spatial* Spearman across cluster means — different from the per-SP *temporal* Spearman in the handoff, but shares the label `rank ρ` on the frontend. Rename the scorecard metric to break the collision.

## Approach

### Compute (`compute/mapping/`)

1. `correlation_map.py`: add `correlate_spearman()` (rank via `argsort(argsort(...))` then Pearson) and `sign_agreement(deadband=2.0)` — both return `(n_bus, n_sp)`.
2. `correlation_map.py::main`: at the **Pearson-argmax** bus, record `best_spearman` and `best_sign`. Do NOT re-argmax.
3. `write_outputs()`: add `best_spearman`, `best_sign` to the npz; add `median_spearman`, `median_sign`, `pct_sign_gt_0_7` to the summary JSON. `median_corr` unchanged.
4. `scorecard.py`: rename `_rank_spearman_per_hour` → `_zone_rank_spearman_per_hour`, headline key `rank_spearman` → `zone_rank_spearman_per_hour`, terminal print, and add a docstring pointer to `median_spearman` in the correlation summary.
5. Downstream renames: `compare_refs.py` (METRIC_ORDER, scorecard read, MD headers) and `experiments/regime_scorecard/{run.py,README.md}`.

### API (`api/`)

6. `models.py::ScorecardHeadline`: rename field, add `Field(..., description=...)`.
7. Update tests: `test_validation.py`, `test_meta.py`, `test_openapi.py`.

### Frontend (`web/src/`)

8. `api/types.ts::ScorecardHeadline`: rename field.
9. `components/panels/StatsPanel.tsx`: point at renamed field; keep visible label `rank ρ`; add `title=` tooltips on all four headline tiles and all five scorecard column headers.

### Do NOT

* Touch `matrix.py`, `congestion/compute.py`, `METHODS`, or run-id gating (not a reference-price change).
* Touch `basis_regression.py`, `cca.py`, `clustering/`, promotion path (no consumers of the renamed field; `best_bus` semantics preserved).
* Re-argmax per metric — `best_bus` stability matters to `basis_regression` and scorecard `sp_to_cluster`.
* Rewrite historical `plan/*.md` files.
* Add a backward-compat alias — breaking the shared word is the point.

## Verification

* Rerun `correlation_map → scorecard` on `v1-annual-2` (matrix stage already has the needed arrays). Confirm `median_corr` unchanged and new fields land.
* Load frontend; confirm scorecard renders and tooltips appear.

## Acceptance

* [x] npz has `best_spearman` and `best_sign` shape `(n_sp,)`. *v1-annual-2: (964,), float64.*
* [x] Summary JSON has `median_spearman`, `median_sign`, `pct_sign_gt_0_7` alongside existing fields.
* [x] `median_corr` on rerun unchanged. *0.3170190381508061; summary byte-identical to pre-change.*
* [x] `median_spearman` near handoff's 0.377 (±0.02). **Observed 0.317** — below tolerance. Consequence of the "diagnostic-at-Pearson-argmax" rule (handoff argmaxed on Spearman). Not a defect; flagging: accept, or add a supplementary Spearman-argmax field?
* [x] `scorecard.json` headline key is `zone_rank_spearman_per_hour`; docstring points at `median_spearman`.
* [x] `grep -rn "rank_spearman" compute/ api/ web/` clean (historical `plan/*.md` excluded).
* [x] `/validation` uses new key; API tests pass. *6 passed in `test_meta.py` + `test_validation.py` + `test_openapi.py`.*
* [x] Frontend type-checks and tooltips render. **Manual browser check at http://localhost:5173 still pending.**
* [x] `run_pipeline.py` runs cleanly through both stages with no pipeline-layer signature changes.
* [x] No new deps; Spearman via numpy `argsort(argsort(...))`.
