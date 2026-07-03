# 0047 — zone-aggregated-scorecard

Type: feat
Branch: feat/0047-zone-aggregated-scorecard

## Goal

* Add `compute/mapping/scorecard.py`: per-derived-zone metrics (corr, sign
  agreement, rank Spearman, within-zone dispersion) over a window.
* Persist `scorecard_<run_id>.json` (per-zone rows + window headline) and
  `scorecard_series_<run_id>.npz` (per-hour `model_Z`, `ercot_Z`).
* Replace legacy `/api/validation` (bus-level modeled_congestion-vs-basis
  Pearson) with a new scorecard endpoint that serves per-zone scores +
  per-hour zone series; mirror the schema in `web/src/api/types.ts`.

## Context

* Depends on S1 core-mapping outputs [[01-correlation-map]] (SP → best_bus)
  and post-CM.6 clustering artifacts (`cluster_labels_<ref>_<algo>_k<K>.npz`
  with `bus_id` + `cluster_id`); SP→zone tag is behavioral (via best_bus →
  cluster), not point-in-polygon.
* Reuses the same reference/matrix pair as CM.1/CM.2: model-side
  `system_lambda_merit_order_model_C` + ERCOT-side `system_lambda_ercot_C`
  from `runs/<run_id>/matrix/congestion_matrices.npz`. Hour axes differ per
  side; intersect on shared hours (v1-120 lands at 107 of 120).
* Legacy `/api/validation` reads `bus_snapshots.basis` and joins the old
  8-zone `bus_load_zones` table — that path is the fragility replacement,
  not the new deliverable.
* Choice of partition (`ref × algo × K`) selects which zoning is scored;
  defaults picked to match post-CM.6 primary path.

## Approach

* Work in: `compute/mapping/scorecard.py` (new), `api/validation.py`
  (replace contents), `api/models.py`, `web/src/api/types.ts`.
* Entry point: `python -m compute.mapping.scorecard --run-id v1-120
  [--algo hierarchical_on_beta] [--k 6] [--deadband 2.0]`.
* Loader: reuse the CM.1 `load_matrices` helper for the (model_C, ercot_C,
  bus_ids, sp_ids, hours) tuple on shared hours.
* SP→zone: read CM.1 `mapping_correlation_<run_id>.npz` for `sp_id →
  best_bus`; read clustering `cluster_labels_<ref>_<algo>_k<K>.npz` for
  `bus_id → cluster_id`; join to yield `sp_id → cluster_id`. Bus→zone comes
  straight from the same labels file.
* Aggregation: for zone Z at hour t, `model_Z(t) = mean model_C[i, t]` over
  buses tagged Z; `ercot_Z(t) = mean ercot_C[j, t]` over SPs tagged Z.
  Zones with fewer than `--min-members` members (default 3) skipped and
  reported in warnings.
* Metrics per zone:
  - `corr = corr(model_Z, ercot_Z)` on shared hours.
  - `sign_agreement = fraction of hours where sign(model_Z)==sign(ercot_Z)`
    with a ±`deadband` $/MWh band (values within excluded from tally).
  - `rank_spearman` (headline): per hour, rank all zones on each side;
    Spearman across zones; average over hours.
  - `dispersion`: within-zone spread of per-bus (model side) and per-SP
    (ercot side) fit — std of `corr(bus_i, ercot_Z)` inside Z; flag outlier
    members with `|z-score| > 2`.
* Serve from a new endpoint at `/validation` (path unchanged for the
  frontend). Query params: `run_id`, `algo`, `k`, optional `deadband`.
  Response: `{ run_id, ref, algo, k, headline: {rank_spearman,
  mean_corr, mean_sign_agreement, n_hours}, zones: [{cluster_id, n_buses,
  n_sps, corr, sign_agreement, dispersion, outliers}], series: {hours,
  by_zone: {cluster_id: {model_Z, ercot_Z}}} }`.
* `api/validation.py`: replace file contents; keep the router variable
  name (`router`) and mount path so `api/main.py` needs no edit. Drop the
  scatter, per-8-zone `by_zone`, `sign_agreement_*`, congested/quiet
  buckets, and all `bus_snapshots`/`bus_load_zones` SQL.
* `api/models.py`: replace `ValidationResponse` and its component models
  with the new schema; delete `CorrelationResult`, `ScatterPoint` if
  unused elsewhere.
* `web/src/api/types.ts`: mirror the new response shape and delete stale
  types.
* Labels source: read the `cluster_labels_<ref>_<algo>_k<K>.npz` artifact
  directly from the run dir (`runs/<run_id>/clustering/`). No new DB
  table — the run artifact is authoritative and versioned by `run_id`.
* Do NOT touch: `compute/matrix.py`, `compute/mapping/{correlation_map,
  basis_regression,cca,diagnostics}.py`, other API routers, `bus_snapshots`
  / `bus_load_zones` schema.

## Sections (commits)

### S1 — scorecard compute module

* Add `compute/mapping/scorecard.py` with:
  - `load_partition(run_id, ref, algo, k)` returning `bus→cluster` and
    `sp→cluster` (via CM.1 `best_bus` join). Fail-fast if artifacts
    missing, with paths in the error.
  - `aggregate(model_C, ercot_C, bus_to_cluster, sp_to_cluster,
    min_members)` returning `hours × zones` matrices `model_Z`, `ercot_Z`
    plus per-zone `n_buses`, `n_sps`.
  - `score(model_Z, ercot_Z, deadband)` returning per-zone
    `{corr, sign_agreement}` + headline `rank_spearman` (mean over hours).
  - `dispersion(model_C, ercot_C, bus_to_cluster, sp_to_cluster, ercot_Z)`
    returning per-zone std + outlier member ids.
* CLI: `--run-id`, `--ref` (default `system_lambda_merit_order`), `--algo`
  (default `hierarchical_on_beta`), `--k` (default `6`), `--deadband`
  (default `2.0`), `--min-members` (default `3`).
* Persist:
  - `runs/<run_id>/mapping/scorecard_<run_id>.json` — headline + per-zone
    rows + params + warnings.
  - `runs/<run_id>/mapping/scorecard_series_<run_id>.npz` — `hours`,
    `cluster_ids`, `model_Z (n_hours, n_zones)`, `ercot_Z (n_hours,
    n_zones)` for the frontend series/scrubber.
* Verify on v1-120: JSON + npz produced; median per-zone corr and rank
  Spearman logged to stdout.

### S2 — API endpoint replacement

* `api/validation.py`: replace contents. New handler reads
  `scorecard_<run_id>.json` and `scorecard_series_<run_id>.npz` from disk
  (path derived from `run_id`), returns the schema below. Router variable
  and mount path unchanged.
* Query params: `run_id` (required), `algo` (default matches compute),
  `k` (default matches compute), `deadband` (optional; if provided,
  compute call is not re-run — deadband applies only at persist time, so
  this stays a read of the artifact). If artifact missing for the
  requested `(algo, k)`, return 404 with a message pointing to the CLI
  command.
* `api/models.py`: add `ScorecardZone`, `ScorecardHeadline`,
  `ScorecardSeries`, `ScorecardResponse` (replaces `ValidationResponse`).
  Delete `CorrelationResult`, `ScatterPoint`.
* Update `api/tests/test_openapi.py` and `api/tests/test_integration.py`
  to cover the new schema (fixtures produce a tiny fake scorecard artifact).
* Verify: `pytest api/tests/` green; `curl localhost:8000/validation?
  run_id=v1-120` returns per-zone rows + series.

### S3 — frontend types

* `web/src/api/types.ts`: replace `ValidationResponse` and drop
  `CorrelationResult`, `ScatterPoint`. Add types matching S2 schema
  (`ScorecardResponse`, `ScorecardZone`, `ScorecardHeadline`,
  `ScorecardSeries`). Do NOT touch UI components in this branch — the
  panel/legend/scrubber wiring lives in a later plan.
* Verify: `npm run build` (or `tsc --noEmit`) succeeds; no unused-type
  warnings from removed types.

## Acceptance

* [x] `compute/mapping/scorecard.py` runs end-to-end on v1-120.
* [x] `runs/v1-120/mapping/scorecard_v1-120.json` reports per-zone
  `{corr, sign_agreement, dispersion, n_buses, n_sps}` + window headline
  `{rank_spearman, mean_corr, mean_sign_agreement, n_hours}`.
* [x] `runs/v1-120/mapping/scorecard_series_v1-120.npz` has aligned
  `hours`, `cluster_ids`, `model_Z`, `ercot_Z` arrays.
* [x] `GET /validation?run_id=v1-120` returns the new schema; legacy
  Pearson calc, scatter, and `bus_load_zones` join removed from
  `api/validation.py`.
* [x] `api/tests/` green.
* [x] `web/src/api/types.ts` matches the new response schema; project
  compiles.
