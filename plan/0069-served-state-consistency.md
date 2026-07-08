# 0069 - served-state-consistency

Type: refactor
Branch: refactor/0069-served-state-consistency

## Goal

* Frontend has zero knowledge of `run_id` / `algo` / `k` — no `VITE_RUN_ID`, no query params, no display of run identity.
* API endpoints take no `run_id` / `algo` / `k` parameter — they open files at fixed paths under `/compute/runs/current/` and read whatever's there.
* One `compute.promote` CLI is the single act that flips a run to "live": rewrites the PVC symlinks *and* the IBP DB pointer in one call, idempotent.

## Context

* Two selection planes today: env vars + files (topology, scorecard) and DB pointer + `implied_binding_proximity.ingest --promote` (IBP). Setting one without the other leaves the API partially serving stale/absent data — observed: `ACTIVE_RUN_ID=v1-annual` set, IBP endpoint still 503'd until `--promote` ran.
* `api/validation.py` currently accepts `run_id` / `algo` / `k` as query params; frontend passes `VITE_RUN_ID` at build. This couples the web bundle to a specific run and forces a rebuild for every switch.
* The IBP DB pointer stays — `implied_binding_proximity_current[layer]` is the right primitive for row-heavy DB-served data. Only the *filesystem*-served state (scorecard, cluster labels) moves to symlinks; the promote CLI is the operator-visible unifier across both planes.

## Approach

* Work in: `compute/promote.py` (new), `api/validation.py`, `api/ercot_state.py`, `api/services/topology_builder.py`, `shared/settings.py`, `web/` (validation call site + `.env.dev`), `ops/deploy/base/api/` configmap references.
* Entry point / primary change: introduce `compute/promote.py` as the single serving-state mutator; strip `run_id` from every API surface.

### Filesystem layout on the PVC

One top-level symlink names the run. Inside the served run, one symlink per served artifact hides the per-cell filename. No `_current` suffixes — the API reads plain names.

```
/compute/runs/
  current  ──▶  v1-annual/              (top-level: which run is served)
  v1-annual/
    mapping/
      scorecard.json                    (symlink → per-cell json below)
      scorecard_series.npz              (symlink → per-cell npz below)
      scorecard_v1-annual_<ref>_<algo>_kN.json      (real files, one per cell exercised)
      scorecard_series_v1-annual_<ref>_<algo>_kN.npz
      mapping_correlation_v1-annual.npz              (per-run, no symlink needed)
      mapping_basis_v1-annual.npz
      mapping_cca_v1-annual.json
    clustering/
      cluster_labels.npz                (symlink → per-cell npz below)
      cluster_labels_<ref>_<algo>_kN.npz             (real files, one per cell)
      summary.json                                    (per-run)
    matrix/
      congestion_matrices.npz           (per-run, no symlink)
    ibp/                                              (feeds DB ingest, not read by API directly)
```

* API always opens `/compute/runs/current/mapping/scorecard.json`, `/compute/runs/current/clustering/cluster_labels.npz`, etc. Both indirection layers (which run, which cell) are invisible to the reader.
* `readlink /compute/runs/current` and `readlink current/mapping/scorecard.json` are the two commands that tell you what's live.

### `compute/promote.py`

* CLI: `python -m compute.promote --run-id <id> --ref <ref> --algo <algo> --k <K>`
* Step 1 — inside `<run_id>/`: `ln -sfn scorecard_<run_id>_<ref>_<algo>_kN.json mapping/scorecard.json` (and the matching `scorecard_series.npz` + `clustering/cluster_labels.npz`). Fails loudly if the target files don't exist.
* Step 2 — top-level: `ln -sfn <run_id> /compute/runs/current` (atomic rename).
* Step 3 — call `implied_binding_proximity.ingest.promote_layer(run_id, layer='ercot')` (extract the pointer-flip helper from `ingest.py` so `promote.py` doesn't shell out).
* `--dry-run` prints what would change without touching anything.
* Idempotent: same args re-run reports "no changes" and does no writes.
* Order matters: cell symlinks flip first (inside the run dir), then top-level `current`, then DB. If step 2 fails, the DB pointer wasn't touched and the previous top-level `current` is still valid.

### `shared/settings.py`

* Delete `ACTIVE_RUN_ID`, `ACTIVE_CLUSTER_ALGO`, `ACTIVE_CLUSTER_K`, `ACTIVE_ERCOT_REF` from the settings dataclass.
* Add `served_run_dir: str = os.environ.get('SERVED_RUN_DIR', '/compute/runs/current')` — the only knob the API reads.

### `api/validation.py`

* Drop `run_id`, `algo`, `k` query params.
* Read `scorecard.json` + `scorecard_series.npz` from `settings.served_run_dir/mapping/`.
* The JSON's own `params` field is the source of truth for algo/k/ref shown in the response — no need to compute or verify them API-side.

### `api/ercot_state.py`

* Read `matrix/congestion_matrices.npz` from `settings.served_run_dir` — no `ACTIVE_ERCOT_REF` selector.
* **Ref selection is coupled to the served scorecard.** The ref is read from `scorecard.json`'s `params.ref` field at request-time (with an in-process cache invalidated on file mtime). Deliberate behavioral change from today, where `ACTIVE_ERCOT_REF` is an independent env var: "which run is served" becomes a single fact, every endpoint derives from it.
* Implication: promoting a scorecard cell built against a different ref automatically switches the ERCOT-state endpoint to the matching ERCOT-side column of the matrix. No separate flip.
* If we ever need to serve a scorecard on one ref and ERCOT-state on another, add a per-endpoint override then — not up front.

### `api/services/topology_builder.py`

* Read `clustering/cluster_labels.npz` from `settings.served_run_dir`.
* `topology.json` cache invalidated on mtime change of the resolved target of `cluster_labels.npz` (`os.stat` follows symlinks; use `os.readlink` + `os.path.getmtime` on the target so a symlink-repoint counts as a change).

### IBP endpoints

* Already read from the DB pointer — no code changes. `compute.promote` makes the pointer flip part of the unified op.

### Optional `/api/meta` endpoint

* Small read-only endpoint returning `{run_id, algo, k, ref, promoted_at}` derived from `readlink /compute/runs/current`, `scorecard.json`'s `params`, and the IBP `promoted_at` column.
* Purpose: the frontend can show run identity in a footer / debug panel *if it wants to*, without any build-time coupling. Frontend still doesn't need it to function.

### Web frontend

* Remove `VITE_RUN_ID` from `.env.dev`, `web/src/`, any build config that reads it.
* Validation call site: drop `run_id` / `algo` / `k` from the request URL; render whatever the API returns.
* Any UI that wants run identity queries `/api/meta` — never a build-time config.

### Configmap `api-config`

* Delete `ACTIVE_RUN_ID`, `ACTIVE_CLUSTER_ALGO`, `ACTIVE_CLUSTER_K`, `ACTIVE_ERCOT_REF`.
* Optionally add `SERVED_RUN_DIR` if overriding the default.

### Rollout order (env vars are load-bearing today — do not delete early)

The `ACTIVE_RUN_ID` / `ACTIVE_CLUSTER_ALGO` / `ACTIVE_CLUSTER_K` / `ACTIVE_ERCOT_REF` keys in `api-config` are read by the current API image. Removing them from the configmap before the new code ships breaks the running API. Sequence:

1. Land the code changes (`compute/promote.py`, new API file-read paths, removed env reads in `shared/settings.py`, `/api/meta`).
2. Roll out the new API image. `ACTIVE_*` env vars stay in the configmap during this step — they become no-ops but do no harm.
3. On the compute pod: `python -m compute.promote --run-id v1-annual --ref system_lambda_merit_order --algo hierarchical_on_beta --k 6` — establishes the symlink tree.
4. Confirm `/api/validation`, `/api/ercot_state`, `/api/meta` serve correctly against the new symlinks.
5. **Delete `ACTIVE_RUN_ID`, `ACTIVE_CLUSTER_ALGO`, `ACTIVE_CLUSTER_K`, `ACTIVE_ERCOT_REF` from `ops/deploy/base/api-config` (or wherever the configmap manifest lives).** Apply and roll the API once more so the pod env matches the manifest.
6. Rebuild and ship the web frontend without `VITE_RUN_ID`.
7. Delete the legacy `scorecard_v1-annual.json` compat symlink on the PVC now that nothing reads it.

Before step 5, grep the tree for `system_lambda_merit_order_hierarchical_on_beta` (the current `ACTIVE_CLUSTER_ALGO` value glues `<ref>_<algo>` together with an underscore and can't be mechanically split — anywhere it appears wants a small cleanup pass to source `ref` and `algo` separately from `scorecard.json`'s `params`).

### Do NOT touch

* `compute/run_pipeline.py`, `compute/mapping/scorecard.py` — per-cell filenames are already correct; writer keeps emitting `scorecard_<run_id>_<ref>_<algo>_kN.json`.
* `compute/implied_binding_proximity/ingest.py` — its `--promote` flag stays; `compute.promote` calls the extracted helper, doesn't replace the CLI.
* IBP DB schema, ERCOT-side ingest, any per-run intermediate files (`mapping_correlation_*.npz`, etc.).

## Acceptance

* [ ] `rg "run_id" web/` returns nothing outside historical comments; `rg "VITE_RUN_ID" web/` returns nothing.
* [ ] `curl /api/validation` (no query params) returns the served scorecard. Any `run_id` / `algo` / `k` query params are silently ignored.
* [ ] `rg "ACTIVE_(RUN_ID|CLUSTER_ALGO|CLUSTER_K|ERCOT_REF)" api/ shared/ ops/` returns nothing outside historical `.md`.
* [ ] `python -m compute.promote --run-id v1-annual --ref system_lambda_merit_order --algo hierarchical_on_beta --k 6` succeeds; re-running is a no-op ("no changes" summary, zero writes).
* [ ] After promote: `readlink /compute/runs/current` → `v1-annual`; `readlink /compute/runs/current/mapping/scorecard.json` → the K=6 hierarchical per-cell file; `SELECT run_id FROM implied_binding_proximity_current WHERE layer='ercot'` returns `v1-annual`.
* [ ] Switching served cell (K=6 → K=8) is one CLI call — no API restart, no image rebuild, no configmap edit. Next `/api/validation` request reflects the new cell (topology cache invalidated on target mtime change).
* [ ] `api/ercot_state.py` has no read of an env var for ref choice; ref comes from `scorecard.json`'s `params.ref`. Promoting a cell with a different `params.ref` immediately changes what `/api/ercot_state` returns.
* [ ] Removing `VITE_RUN_ID` from the web build produces a bundle that renders correctly against the API.
* [ ] `GET /api/meta` returns `{run_id, algo, k, ref, promoted_at}` matching the current symlink targets and DB pointer.
