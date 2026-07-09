# 0074 - regime-scorecard-diagnostic

Type: feat
Branch: feat/0074-regime-scorecard-diagnostic

## Goal

* Ship a one-shot experiment that recomputes the existing scorecard metrics per **regime bin**, so we can see whether pooled `mean_corr` is diluted by slack hours.
* Emit per-bucket `mean_corr`, `rank_spearman`, `mean_sign_agreement`, `n_hours` alongside a pooled row, from existing `v1-120` / `v1-annual` artifacts — no OPF re-run.
* Support three bin schemes minimally: `congestion_magnitude:q4`, `net_load:q4`, `binding_active`.

## Context

* Step 1 of [[handoff-regime]]. If per-regime tracking is materially stronger than pooled (rough prediction: ~2× on `mean_corr` in the top net-load quartile), the rest of the regime-conditioned roadmap (`regime_partition` stage, `--regime-mode stacked` clustering, weighted β) is justified. If it isn't, that whole line is moot and we drop it.
* On `q4`: the handoff's `net_load:q4` is a bin-spec — **4 quantile buckets** — not "quarter 4" of the year and not "top quartile only". The diagnostic reports per-bucket metrics for all 4 buckets so we can see the shape of the tracking-vs-regime curve. Which bucket concentrates the signal (if any) is the finding.
* Data plumbing: `compute/runs/<run>/matrix/congestion_matrices.npz` already contains everything needed for the `congestion_magnitude` binner. `binding_active` needs a per-hour "any bind" signal (available from the model-side matrix; nonzero column-sum on `system_lambda_merit_order_model_C` is a serviceable proxy). `net_load` needs ERCOT load + wind + solar time series — these live under `compute/ercot/` already; we add a thin loader.
* **Ref pair axis (relation to `compute/congestion/compute.py`)**: the ~10 methods in `METHODS` produce ~10 model_C/ercot_C matrix pairs. `correlation_map.py` and `scorecard.py` already run on **one (model_ref, ercot_ref, partition_ref) tuple at a time** — defaults `system_lambda_merit_order / system_lambda / system_lambda_merit_order`. The regime diagnostic inherits that: one invocation = one pair × N regime schemes. To ask "does regime-conditioning change which pair wins", drive multiple invocations (natural extension: a regime axis on top of `compute/mapping/compare_refs.py` and its `pairs/default.json`). That extension is **out of scope for this ticket** — call it 0074b if it materializes. Ship the single-pair diagnostic first; if per-bucket tracking is flat, the pair sweep is moot too.
* No changes to `compute/mapping/scorecard.py` (pooled scorecard stays the promoted baseline). No changes to `compute/run_pipeline.py` `STAGES`. No DB writes.

## Approach

Two directories touched, both under `compute/`:

* `compute/regimes/` (new) — **library-only** helpers. Binners and a covariate loader. Reusable by the eventual `regime_partition` stage (step 2 of the handoff).
* `compute/experiments/regime_scorecard/` (new) — the CLI driver. Uses `compute/regimes/` + existing `compute/mapping/scorecard.py` internals. Nothing else consumes this; it's a diagnostic.

### Files to add

* `compute/regimes/__init__.py`
* `compute/regimes/binners.py`
  * `bin_hours(scheme: str, *, hours, model_C, ercot_C, covariates) -> np.ndarray` returning an int per hour (`-1` for excluded).
  * Schemes: `"congestion_magnitude:q4"` (quantile bucket on `|ercot_C|.mean(axis=0)` per hour), `"net_load:q4"` (quantile bucket on load − wind − solar), `"binding_active"` (0/1 on whether any line binds in the hour; source = `system_lambda_merit_order_model_C` column-nonzero proxy — document the proxy).
  * Generic `qN` parser (`qN` → `N` quantile buckets) so `q3`, `q5` etc. work without new code.
* `compute/regimes/covariates.py`
  * `load_hourly_covariates(run_id, hours) -> dict[str, np.ndarray]` returning `{"load", "wind", "solar", "system_lambda"}` aligned to the matrix `hours` axis. Reuse existing ERCOT ingest tables — do not re-fetch. Missing covariates return NaN vectors and the caller logs which schemes become unavailable.
* `compute/experiments/regime_scorecard/__init__.py`
* `compute/experiments/regime_scorecard/run.py` — CLI entry point (see below).
* `compute/experiments/regime_scorecard/README.md` — one page: what it does, what `q4` means, how to read the output table, how to interpret pooled-vs-per-bucket.

### CLI shape

```
python -m compute.experiments.regime_scorecard.run \
    --run-id v1-120 \
    --bins net_load:q4,congestion_magnitude:q4,binding_active \
    --ref system_lambda_merit_order \
    --model-ref system_lambda_merit_order \
    --ercot-ref system_lambda \
    --algo hierarchical_on_beta \
    --k 6 \
    [--deadband 2.0] [--min-members 3]
```

`--bins` accepts a comma list; one output file per scheme. Multiple schemes in one invocation share matrix + partition loads. `--model-ref` / `--ercot-ref` / `--ref` mirror `compute/mapping/scorecard.py` exactly — one pair per invocation, sweep by scripting.

### Reuse, not fork

`run.py` imports and calls the existing `compute.mapping.scorecard` primitives — do NOT copy-paste them:

* `load_matrices`, `load_partition`, `aggregate` — reused as-is.
* `score(model_Z, ercot_Z, deadband)` — call once per bucket by slicing `model_Z[mask]` and `ercot_Z[mask]` along the hour axis (both are `(n_hours, n_zones)`).
* Pooled row = calling `score` on the unmasked matrices; it must reproduce the number the existing scorecard prints for the same `(run_id, ref, algo, k)`. Assert this in the run's stdout as a sanity check.

### Output layout

* `runs/<run>/experiments/regime_scorecard/<run>_<ref>_<algo>_k<K>_<bins>.json`
  ```json
  {
    "run_id": "v1-120",
    "params": {"ref": "...", "algo": "...", "k": 6, "bins": "net_load:q4", ...},
    "covariate_source": {"load": "ercot.load_actual", ...},
    "buckets": [
      {"id": 0, "label": "Q1", "range": [lo, hi], "n_hours": 120,
       "rank_spearman": 0.31, "mean_corr": 0.18, "mean_sign_agreement": 0.54,
       "hours": ["2025-01-04T03:00Z", "2025-01-04T04:00Z", ...]},
      {"id": 1, ...}, {"id": 2, ...}, {"id": 3, ...},
      {"id": null, "label": "pooled", "n_hours": 480, "hours": null,
       "rank_spearman": ..., "mean_corr": ..., "mean_sign_agreement": ...}
    ],
    "warnings": [...]
  }
  ```
  Per-bucket `"hours"` is the concrete timestamp list that fell in the bucket — makes "why did Q4 pop?" answerable by eyeballing (are they all July afternoons? all winter storm hours?). Pooled row leaves it `null` to avoid duplicating the full run window.
* Stdout: a small formatted table so `docker compose run` output is directly readable.

### Do NOT touch

* `compute/mapping/scorecard.py`, `compute/mapping/correlation_map.py`, `compute/run_pipeline.py`, `compute/promote.py`.
* Anything under `api/`, `web/`, `db/`. This is a diagnostic; nothing gets served.
* Existing `runs/v1-120/mapping/scorecard_*.json` — pooled artifacts remain the promoted baseline.

## Acceptance

* [ ] `compute/regimes/binners.py` provides `bin_hours` with `congestion_magnitude:q4`, `net_load:q4`, `binding_active`; generic `qN` parser works for `N in {2,3,4,5,8}`.
* [ ] `compute/regimes/covariates.py` returns per-hour vectors aligned to matrix `hours`; missing sources yield NaN + a logged warning naming the affected schemes.
* [ ] `python -m compute.experiments.regime_scorecard.run --run-id v1-120 --bins congestion_magnitude:q4 --ref system_lambda_merit_order --algo hierarchical_on_beta --k 6` writes exactly one JSON under `runs/v1-120/experiments/regime_scorecard/` and prints a per-bucket + pooled table to stdout.
* [ ] The pooled row's `rank_spearman`, `mean_corr`, `mean_sign_agreement` match the existing `runs/v1-120/mapping/scorecard_v1-120_system_lambda_merit_order_hierarchical_on_beta_k6.json` headline to within float tolerance (asserted in the run script).
* [ ] Running with `--bins net_load:q4` on `v1-120` produces 4 non-empty buckets (hour count per bucket within ±1 of `n_hours / 4`).
* [ ] Running with `--bins binding_active` on `v1-120` produces 2 buckets (`inactive`, `active`) with `n_hours` summing to total.
* [ ] Re-running with the same args overwrites its own cell but does NOT touch anything under `runs/<run>/mapping/`.
* [ ] `git grep` shows no imports of `compute.experiments.regime_scorecard` from outside `compute/experiments/regime_scorecard/`.
* [ ] Same invocation succeeds against `v1-annual` once the backfill/pipeline rerun completes — no code change needed. (This is the run the writeup will use; `v1-120` is the smoke.)
