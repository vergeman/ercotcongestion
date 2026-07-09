# 0079 - model-correlation-scorecard

Type: feat
Branch: feat/0079-model-correlation-scorecard

## Goal

* Serve `mapping_correlation_summary_<run_id>.json` (per-SP model-vs-ERCOT correlation summary, produced by `compute/mapping/correlation_map.py`) through a new API endpoint.
* Add a `mapping/mapping_correlation_summary.json` symlink to `compute.promote`, alongside the existing per-cell scorecard symlinks, so the API can read it at a fixed path.
* Render a new "Model Correlation" headline strip in `StatsPanel.tsx`, parallel to the existing Cluster Correlation strip, sourced from the new endpoint.

## Context

* `api/validation.py` already serves a *cell*-scoped scorecard (`mapping/scorecard.json` + `.npz`, keyed by `run_id/ref/algo/k`) computed on zone-aggregated clusters. That is unrelated data — do not conflate the two.
* `mapping_correlation_summary_<run_id>.json` is *run*-scoped only (no `ref/algo/k` in the filename) — it's a flat single-object summary of per-SP-to-best-bus correlation (964 SP/bus pairs for the current run), not a per-zone array. There is no `zones: []` list in this artifact.
* Confirmed schema (from `compute/runs/v1-annual-2/mapping/mapping_correlation_summary_v1-annual-2.json`):
  ```json
  {
    "run_id": "v1-annual-2",
    "model_ref": "kkt_perbus",
    "ercot_ref": "zone_local_spp",
    "var_threshold": 1.0,
    "n_sp": 964,
    "n_bus": 2544,
    "n_sp_dropped": 0,
    "n_bus_dropped": 50,
    "pct_gt_0_7": 0.0,
    "pct_gt_0_5": 0.0197,
    "median_corr": 0.317,
    "median_spearman": 0.317,
    "median_sign": 0.4696,
    "pct_sign_gt_0_7": 0.3517
  }
  ```
  Documented in `compute/runs/README.md:117-131`. Field names/types are stable — no `zones`/`series`/`params` sub-objects needed.
* Because the artifact is not `(ref, algo, k)`-parameterized, `compute.promote`'s existing `_cell_targets()` list can host the new symlink entry unchanged (the function already receives `run_id`; `ref/algo/k` are simply unused for this entry).

## Approach

* Work in: `compute/promote.py`, `api/models.py`, `api/validation.py`, `api/main.py`, `web/src/api/types.ts`, `web/src/api/client.ts`, `web/src/App.tsx`, `web/src/components/panels/StatsPanel.tsx`
* Entry point / primary change: new `MappingCorrelationSummary` pydantic model + new `GET /mapping_correlation` route (module `api/mapping_correlation.py`, mirroring `api/validation.py`'s structure).
* **compute/promote.py**: add `("mapping/mapping_correlation_summary.json", f"mapping_correlation_summary_{run_id}.json")` to `_cell_targets()` (or a new `_run_targets()` list run once per `run_id`, not per cell, if `_cell_targets()` is called multiple times per promote across cells — check call sites before choosing). Confirm the "refuse if target missing" pre-check (lines ~96-109) covers this new entry so a bad promote fails loudly.
* **api/models.py**: add `MappingCorrelationSummary` pydantic model with fields exactly matching the JSON schema above (`run_id: str, model_ref: str, ercot_ref: str, var_threshold: float, n_sp: int, n_bus: int, n_sp_dropped: int, n_bus_dropped: int, pct_gt_0_7: float, pct_gt_0_5: float, median_corr: float, median_spearman: float, median_sign: float, pct_sign_gt_0_7: float`).
* **api/mapping_correlation.py** (new file): `GET /mapping_correlation` reads `Path(settings.served_run_dir) / "mapping" / "mapping_correlation_summary.json"`, 503s with a `python -m compute.promote ...` hint if missing (mirror `validation.py`'s error style), returns `MappingCorrelationSummary(**payload)`.
* **api/main.py**: import the new module and `app.include_router(mapping_correlation.router, tags=['validation'])` alongside the existing `validation.router` registration.
* **web/src/api/types.ts**: add `MappingCorrelationSummary` TS interface mirroring the pydantic model 1:1 (same field names/casing — no camelCase conversion, matching the existing `ScorecardResponse` convention).
* **web/src/api/client.ts**: add `fetchMappingCorrelation(): Promise<MappingCorrelationSummary>` hitting `${BASE}/mapping_correlation`, mirroring `fetchScorecard()`.
* **web/src/App.tsx**: add `mappingCorrelation` state (`useState<MappingCorrelationSummary | null>(null)`), a mount-effect calling `fetchMappingCorrelation().then(setMappingCorrelation).catch(() => setMappingCorrelation(null))` alongside the existing scorecard effect, and pass `mappingCorrelation={mappingCorrelation}` into `<StatsPanel .../>`.
* **StatsPanel.tsx**: add `mappingCorrelation: MappingCorrelationSummary | null` to `Props`. Add a new `panel-section` immediately after the existing Cluster Correlation headline block (after line 201), styled as a `scorecard-headline`-style strip (reuse the existing `.scorecard-headline` / `.scorecard-headline__item` CSS classes — do not duplicate the styles). Header: `Model Correlation · {mappingCorrelation.model_ref} → {mappingCorrelation.ercot_ref}`. Items: `n_sp`, `n_bus`, `median_corr` (2dp), `median_spearman` (2dp), `median_sign` (as %), `pct_gt_0_5` (as %), `pct_gt_0_7` (as %). Only render the section when `mappingCorrelation` is non-null (same pattern as `{scorecard && (...)}`).
* Do NOT touch: `api/validation.py`'s existing route/model (`ScorecardResponse` family), `compute/mapping/correlation_map.py` (artifact producer, out of scope — already writes correct output), the per-zone `scorecard-rows` table in `StatsPanel.tsx` (this new data has no per-zone rows to render).

## Acceptance

* [ ] `python -m compute.promote --run-id <id> --ref <ref> --algo <algo> --k <k>` creates/updates `compute/runs/<id>/mapping/mapping_correlation_summary.json` as a symlink to `mapping_correlation_summary_<id>.json`, and fails with a clear error if the target file is missing.
* [ ] `GET /api/mapping_correlation` returns 200 with the full `MappingCorrelationSummary` payload when a run is promoted, and 503 with a `compute.promote` hint when the symlink is absent.
* [ ] `web/src/api/client.ts::fetchMappingCorrelation()` successfully fetches and parses the response into `MappingCorrelationSummary`.
* [ ] StatsPanel renders a "Model Correlation" section with `model_ref → ercot_ref` in the header and the 7 stat items, positioned directly below the existing "Cluster Correlation" section, only when data is loaded (no visual regression when it's null/loading).
* [ ] No changes to existing `/api/validation` response shape or the Cluster Scorecard table.
