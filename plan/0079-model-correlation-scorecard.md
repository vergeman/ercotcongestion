# 0079 - model-correlation-scorecard

Type: feat
Branch: feat/0079-model-correlation-scorecard

## Goal

* Fold the per-SP `mapping_correlation_summary_<run_id>.json` artifact into the existing `/api/validation` response as an optional field.
* Add a `mapping/mapping_correlation_summary.json` symlink to `compute.promote`.
* Render a "Model Correlation" headline strip in `StatsPanel.tsx`, above the existing Cluster Correlation strip.

## Context

* `mapping_correlation_summary_<run_id>.json` is run-scoped (no `ref/algo/k`), written by `compute/mapping/correlation_map.py`. Flat object, no per-zone array — distinct from the cell-scoped `scorecard.json` zone data.
* Schema: `run_id, model_ref, ercot_ref, var_threshold, n_sp, n_bus, n_sp_dropped, n_bus_dropped, pct_gt_0_7, pct_gt_0_5, median_corr, median_spearman, median_sign, pct_sign_gt_0_7`. Documented in `compute/runs/README.md:117-131`.
* Originally planned as a separate `/api/mapping_correlation` endpoint; merged into `/api/validation` instead to avoid a second round-trip — the frontend already loads scorecard on mount and this data shares the same lifecycle.

## Approach

* Work in: `compute/promote.py`, `api/models.py`, `api/validation.py`, `web/src/api/types.ts`, `web/src/components/panels/StatsPanel.tsx`
* **compute/promote.py**: `_cell_targets()` gets a new entry `("mapping/mapping_correlation_summary.json", f"mapping_correlation_summary_{run_id}.json")` — run-scoped but harmless to include since `_cell_targets()` runs once per promote.
* **api/models.py**: `MappingCorrelationSummary` pydantic model; `ScorecardResponse` gets `mapping_correlation: MappingCorrelationSummary | None = None`.
* **api/validation.py**: `_load_mapping_correlation()` reads `mapping/mapping_correlation_summary.json`, returns `None` if missing (soft-fail, doesn't affect the existing scorecard 503 logic).
* **web/src/api/types.ts**: `MappingCorrelationSummary` interface; `ScorecardResponse.mapping_correlation: MappingCorrelationSummary | null`.
* **web/src/components/panels/StatsPanel.tsx**: `const mappingCorrelation = scorecard?.mapping_correlation ?? null;` — no new prop. New `panel-section` rendered above "Cluster Correlation", reusing `.scorecard-headline` CSS. Header: `Model Correlation · {model_ref} → {ercot_ref}`. Items, in order: median ρ (spearman), median r (pearson), median sign%, r>0.5 — all via `fmt(..., 2)`. `fmt()` updated to set `minimumFractionDigits` alongside `maximumFractionDigits` so 2dp values don't drop trailing zeros.
* Do NOT touch: `compute/mapping/correlation_map.py`, the per-zone `scorecard-rows` table.

## Acceptance

* [x] `compute.promote` creates `mapping/mapping_correlation_summary.json` as a symlink, refuses to promote if the target file is missing.
* [x] `GET /api/validation` includes `mapping_correlation` (populated when the symlink resolves, `null` otherwise); no change to the rest of the response shape.
* [x] StatsPanel renders "Model Correlation" above "Cluster Correlation", showing median ρ, median r, median sign%, r>0.5 with consistent 2-decimal formatting; section omitted when `mapping_correlation` is null.
* [x] `tsc --noEmit` passes.
