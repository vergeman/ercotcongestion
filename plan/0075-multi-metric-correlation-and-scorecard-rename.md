# 0075 - multi-metric-correlation-and-scorecard-rename

Type: feat
Branch: feat/0075-multi-metric-correlation-and-scorecard-rename

## Goal

* Export Spearman and sign-agreement alongside Pearson from `correlation_map` so per-SP mapping quality can be read under all three metrics from a merged-to-master run.
* Rename the scorecard's headline `rank_spearman` to `zone_rank_spearman_per_hour` end-to-end (compute → API model → API tests → frontend) so the metric name self-describes what it measures.
* Surface metric definitions in the frontend via header-column tooltips so a reader doesn't have to open a plan file to know what `rank ρ` means.
* Preserve the current Pearson-driven `best_bus` / `topk` selection — Spearman and sign are additive columns, not a change to which bus each SP maps to.

## Context

* `plan/handoff-0072-zonal-partial-credit.md` established that `kkt_perbus × zone_local_spp` is the recommended pair. Its strongest evidence (Spearman median 0.377, sign p99 0.944) came from `experiments/load_weighted_ablation/ablate_load_weighted.py` on branch `experiment/0072-zone-reference-price`, which never landed on master.
* On master, only Pearson exists in `mapping_correlation_summary_<run_id>.json` (median 0.317, pct>0.5 ~2%), which understates the finding relative to the handoff.
* The scorecard exports a different statistic under the same word "Spearman" (`compute/mapping/scorecard.py::_rank_spearman_per_hour` — per-hour rank across ~4 cluster means) that is not comparable to the per-SP temporal Spearman in the handoff. This was a live source of user confusion; the shared "rank ρ" label in `StatsPanel` reinforces it on the frontend.
* Recommendation #3 in the handoff explicitly asks for this: extend the compare/scorecard harness to compute all three metrics using helpers that already existed in the ablation script.

## Approach

* Work in: `compute/mapping/`, `api/`, `web/src/`.
* Entry point / primary change: `correlate()` and `write_outputs()` in `correlation_map.py`; headline dict in `scorecard.py`; `ScorecardHeadline` in `api/models.py`; `ScorecardHeadline` type + `StatsPanel` header row on the web.

### Compute side

* Step 1 — In `compute/mapping/correlation_map.py`, add two helpers next to `correlate()`:
  * `correlate_spearman(model_C, ercot_C) -> np.ndarray` — rank each row (bus / SP) over time via `argsort(argsort(...))`, then Pearson on ranks. Returns the same (n_bus, n_sp) shape as `correlate()`.
  * `sign_agreement(model_C, ercot_C, deadband=2.0) -> np.ndarray` — fraction of jointly-finite hours where `sign(model_i[t]) == sign(sp_j[t])` under a `$deadband` threshold. Same (n_bus, n_sp) shape.
* Step 2 — In `correlation_map.py::main`, call the two new helpers alongside the existing Pearson `correlate()`. Each SP keeps its **Pearson-argmax** `best_bus`; alongside `best_corr`, record `best_spearman` and `best_sign` — the Spearman and sign values *at the Pearson-argmax bus*. Do NOT re-argmax per metric.
* Step 3 — Extend `write_outputs()` to add columns `best_spearman`, `best_sign` to the npz and to add three headline fields to the summary JSON: `median_spearman`, `median_sign`, `pct_sign_gt_0_7`. Keep `median_corr` unchanged for backward compatibility.
* Step 4 — In `compute/mapping/scorecard.py`:
  * Rename `_rank_spearman_per_hour` → `_zone_rank_spearman_per_hour`.
  * Rename headline key `rank_spearman` → `zone_rank_spearman_per_hour`. Update the terminal print at the end of `main()` (`headline: rank_spearman=...` → `zone_rank_spearman_per_hour=...`).
  * Add one sentence to the module docstring: *"Headline `zone_rank_spearman_per_hour` is a per-hour spatial rank across cluster means. For per-SP temporal rank correlation, see `mapping_correlation_summary_<run_id>.json::median_spearman`."*
* Step 5 — Update the two other compute-side consumers of `rank_spearman`:
  * `compute/mapping/compare_refs.py` — rename the field in its output rows and column header (lines 46, 91, 98, 103, 202, 226) to `zone_rank_spearman_per_hour`.
  * `compute/experiments/regime_scorecard/run.py` — rename field references (lines 123, 180, 185, 225, 265, 269) to `zone_rank_spearman_per_hour`. Update the README's example JSON blocks (`compute/experiments/regime_scorecard/README.md`) so the key names match.

### API side

* Step 6 — In `api/models.py::ScorecardHeadline` (line 194), rename the field `rank_spearman: float | None` → `zone_rank_spearman_per_hour: float | None`. Add a `Field(..., description=...)` describing the metric ("mean over hours of per-hour spatial rank correlation across the derived-zone means; not comparable to the per-SP temporal Spearman in mapping_correlation_summary").
* Step 7 — Update the API tests (`api/tests/test_validation.py:44,83`, `api/tests/test_meta.py:36`, `api/tests/test_openapi.py:49`) to use the new key name. No behavior changes.

### Frontend side

* Step 8 — In `web/src/api/types.ts::ScorecardHeadline` (line 148), rename `rank_spearman` → `zone_rank_spearman_per_hour`.
* Step 9 — In `web/src/components/panels/StatsPanel.tsx`:
  * Update the reference at line 80 to `scorecard.headline.zone_rank_spearman_per_hour`.
  * Keep the visible label at line 78 as `rank ρ` — panel space is tight and hover copy carries the disambiguation.
  * Add a `title=` attribute on the headline item (line 77 wrapper) with a one-line description: *"Per-hour spatial Spearman across the derived cluster means, averaged over hours. Not per-SP temporal — see the correlation map summary."* Repeat the pattern (label + `title=`) on `mean r`, `sign%`, and `hours` so all four headline tiles have hover context.
  * Add `title=` attributes on the scorecard-row-head column labels (line 111-115 `zone / buses / corr / sign% / disp`) with one-line descriptions.
* Step 10 — `web/src/api/client.ts` needs no changes — it forwards the JSON blob to typed consumers, which type-check against the renamed field automatically.

### Verification

* Step 11 — Rerun the pipeline against `runs/v1-annual-2` (matrix stage already produced the required `kkt_perbus_*` and `zone_local_spp_*` arrays; only `correlation_map` and `scorecard` need to re-execute). Confirm `median_corr` is unchanged and the new fields land.
* Step 12 — With the API pointed at `v1-annual-2`, load the frontend and confirm the scorecard renders, the `zone rank ρ/hr` label shows a value, and tooltips appear on hover.

* Do NOT touch: `compute/matrix.py`, `compute/congestion/compute.py`, the `METHODS` dict, or any run-id gating. This is a metrics-export + rename change, not a reference-price change.
* Do NOT touch: `compute/mapping/basis_regression.py`, `cca.py`, `clustering/`, or the promotion path — none of them consume the renamed field, and `best_bus` / `best_corr` semantics are preserved.
* Do NOT re-argmax per metric. Consumers downstream of `best_bus` (basis_regression, scorecard's `sp_to_cluster` derivation) rely on Pearson-argmax stability; the new Spearman/sign columns are diagnostic-at-argmax only.
* Do NOT rewrite historical plan/handoff `.md` files that mention `rank_spearman`. Those are frozen historical records; leave them.
* Do NOT delete the old field name in-place with a backward-compat alias. This is a name that already caused confusion — the whole point is to break the shared word.

## Acceptance

* [ ] `mapping_correlation_<run_id>.npz` contains `best_spearman` and `best_sign` arrays of shape (n_sp,).
* [ ] `mapping_correlation_summary_<run_id>.json` contains `median_spearman`, `median_sign`, `pct_sign_gt_0_7` alongside the existing `median_corr`, `pct_gt_0_5`, `pct_gt_0_7`.
* [ ] `median_corr` value on a re-run of `v1-annual-2` is unchanged to within 1e-9 vs. the pre-change value (0.317…).
* [ ] `median_spearman` on `v1-annual-2` lands in the neighborhood of the handoff's 0.377 for `kkt × zone_local_spp` (accept ±0.02 given the rectangle differs by ~50 buses vs. `v1-annual-zonelocal`).
* [ ] `scorecard.json` headline key is `zone_rank_spearman_per_hour` (no `rank_spearman` remains); the module docstring in `scorecard.py` names the per-SP metric as the comparison partner.
* [ ] `grep -rn "rank_spearman" compute/ api/ web/` returns no hits (historical `plan/*.md` excluded).
* [ ] API `/validation` response uses the new key; `pytest api/tests/` passes with the renamed field.
* [ ] Frontend type-checks (`web/`) and the scorecard headline renders `rank ρ` (label unchanged); hovering any headline tile or scorecard column header shows a definition tooltip.
* [ ] `run_pipeline.py` runs cleanly through `correlation_map → scorecard` on `v1-annual-2` with no signature changes required at the pipeline layer.
* [ ] No new dependency added; Spearman implemented via numpy `argsort(argsort(...))` (matches the handoff's Pearson-invariance-to-row-mean approach).
