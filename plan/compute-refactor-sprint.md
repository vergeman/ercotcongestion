# Pipeline Integration Sprint — Phase 3 → end-to-end orchestrator

## Context

Phase 3 components (congestion calculation, matrix persistence, zonal clustering) are all built and individually validated on an 11-snapshot smoke run. They work in isolation but aren't chained: each is invoked manually, outputs land loose in source directories with ad-hoc names (`congestion_matrix_final-merit.json`, `congestion_matrices_test-persist.npz`, `ercot_congestion_results_ercot-final-merit.json`, …), and the code itself still lives under `compute/experiments/` — the proof-of-concept location. The `zonal_clustering` stage already established a `runs/<run_id>/` output convention; nothing upstream of it has.

Three structural problems will compound the moment we scale sample size or push toward Phase 4:

1. **Experiments/ is now production code.** `congestion_calculation/` and `zonal_clustering/` aren't speculative anymore — they're the pipeline. Keeping them under `experiments/` masks that, forces sibling `experiments/*` scripts to import via `sys.path.insert('/compute')` hacks, and makes the eventual integration into `write_snapshots.py` harder than it should be.
2. **Artifact sprawl.** At 11 snapshots, congestion JSON is ~6.4 MB. At 120 snapshots it is ~70 MB; at 500, ~320 MB. Multiple ref-method runs at full scale would litter source directories with hundreds of MB of indistinguishable files.
3. **No shared run identity.** A "run" today is a name the user remembers to pass to each stage. Re-running stage 3 against stage 2 outputs from a different sample is silently possible. Phase 4 will need matched (congestion, matrix, clusters) triples from a known input window — easier to build that on top of a run_id contract than to retrofit.

This sprint **(a)** lifts the production-grade experimental code into first-class modules under `compute/`, **(b)** standardizes per-run output layout, **(c)** threads a shared `--run-id` through every stage, and **(d)** adds a single orchestrator that chains `snapshots → congestion → matrix → clustering`. `compute/write_snapshots.py` and `compute/test_snapshot.py` are preserved unchanged — they keep working through and after the sprint. Eventual integration into `write_snapshots.py` is a follow-on sprint, not this one.

Sample size steps from 20 → 120 snapshots (30 per regime via the existing extractor) — large enough to stress the new pipeline at ~6× current scale, small enough to complete in minutes so the orchestrator is iterable. Phase 4 (validation framework) is the next sprint, and will consume the per-run artifact layout this sprint defines.

## Scope

### 1. Lift experimental code to first-class `compute/` modules

The production-grade pieces under `compute/experiments/` move out. Mirror the `runs/` subdirectory naming (`congestion`, `matrix`, `clustering`) so source layout matches output layout.

Target structure:

```
compute/
  __init__.py                    # new — makes compute a package
  snapshot.py                    # existing (untouched)
  test_snapshot.py               # preserved (untouched)
  write_snapshots.py             # preserved (untouched)
  operating_data_adapter.py      # existing
  operating_conditions.py        # existing
  config.py, constants.py, fragility.py, ptdf_lodf.py, contingency.py, ...

  congestion/                    # lifted from experiments/congestion_calculation/
    __init__.py                  # new
    compute.py                   # was experiments/.../congestion.py — compute_congestion + diagnostics
    system_lambda_estimators.py  # was experiments/.../system_lambda_estimators.py (kept as-is)
    snapshot_runner.py           # was experiments/.../congestion_snapshot.py — CLI/driver
    ercot_runner.py              # was experiments/.../ercot_congestion_snapshot.py — CLI/driver

  matrix.py                      # was experiments/.../congestion_matrix.py
                                 # single file at top of compute/; drops `congestion_` prefix (directory context gone)

  clustering/                    # lifted from experiments/zonal_clustering/
    __init__.py                  # new
    algorithm.py                 # was experiments/zonal_clustering/clustering.py — the 5 cluster fns
    diagnostics.py               # was experiments/zonal_clustering/diagnostics.py (kept as-is)
    polygons.py                  # was experiments/zonal_clustering/polygons.py (kept as-is)
    select_zones.py              # was experiments/zonal_clustering/select_zones.py (kept as-is)
    runner.py                    # was experiments/zonal_clustering/run_clustering.py — CLI sweep

  sample_specs/                  # was compute/profiling/
    __init__.py                  # new
    extract_dates.py             # was extract_sample_snapshot_dates.py
    reference_dates.json

  run_pipeline.py                # new orchestrator
  runs/                          # outputs (gitignored)

  experiments/                   # what stays — genuine POC space
    interface_flow_diagnostic/
    system_lambda/               # original POC for the estimators that now live in compute/congestion/
    zonal_load/                  # cap_sweep, permian_backbone, compare_zonal_lmp, ...
    preprocess/                  # any remaining bus-zone-assignment scripts (if not also lifted)
```

**Filename rule:** rename to short names that describe the file's role within the package — the package name supplies the subject. So `compute/congestion/compute.py` is read as "the compute module of the congestion package", `compute/clustering/algorithm.py` as "the algorithm module of the clustering package", and so on. `system_lambda_estimators.py`, `diagnostics.py`, `polygons.py`, `select_zones.py` keep their names — they're already short and role-descriptive. Git blame is preserved through `git mv` (rename detection survives small content edits).

**Imports:** the `sys.path.insert(0, '/compute')` hacks at the top of every lifted script are deleted. With `compute/__init__.py` in place, intra-package imports become package-style (`from compute.snapshot import compute_snapshot_batch`, or relative `from .congestion import compute_congestion` within a subpackage). Docker runtime needs `PYTHONPATH` to include the project root (or `compute` to be installed editable) — likely already true since the sys.path hacks were the workaround for it not being.

**What stays in `experiments/`:** anything still genuinely exploratory. `zonal_load/*` scripts (cap_sweep, permian_backbone, etc.), `interface_flow_diagnostic/`, `system_lambda/`, `preprocess/`. These get import-path updates (they currently `from ... import` the now-lifted modules), but no structural change.

### 2. Standardize per-run output layout

Every artifact for run `<run_id>` lands under `compute/runs/<run_id>/`, with stage subdirs that mirror the source package names:

```
compute/runs/<run_id>/
  meta.json                       # run_id, created_at, dates-file path + SHA-256, git sha, per-stage status
  reference_dates.json            # copy of the dates file used (provenance)
  congestion/
    model_results.json            # was: congestion_results_<name>.json
    ercot_results.json            # was: ercot_congestion_results_<name>.json
  matrix/
    congestion_matrices.npz       # was: congestion_matrices_<name>.npz
    matrix_summary.json           # was: congestion_matrix_<name>.json
  clustering/
    summary.json
    zones_<ref>_<algo>_k<K>.geojson
    ercot_sp_labels_<ref>_<algo>_k<K>.csv
```

The existing `experiments/zonal_clustering/runs/test-persist/` artifacts migrate to `compute/runs/legacy-test-persist/clustering/`.

### 3. Thread `--run-id` through stage entry points

After the lift, the four stage CLIs live in their first-class homes. Each gets `--run-id` while keeping existing explicit-path flags for ad-hoc/debug use.

* `compute/congestion/snapshot_runner.py` — already accepts `--run-id`. Change: when set, default output path to `compute/runs/<run_id>/congestion/model_results.json.gz`.
* `compute/congestion/ercot_runner.py` — add `--run-id`; default output path to `compute/runs/<run_id>/congestion/ercot_results.json.gz`.
* `compute/matrix.py` — currently takes `--model-results PATH`. Add `--run-id`; derive inputs from `runs/<run_id>/congestion/` and outputs to `runs/<run_id>/matrix/`.
* `compute/clustering/runner.py` — currently takes `--matrices` and `--out-dir`. Add `--run-id`; derive both. Drop the inner `runs/<name>/` nesting under this script — the unified tree replaces it.

### 4. Intermediate artifact lifecycle

The per-record congestion JSONs (`model_results.json`, `ercot_results.json`) are the audit-friendly inputs to the matrix stage. They grow linearly with N snapshots × N buses × N reference methods — at 11 snapshots ~6.4 MB, at 120 ~70 MB, at 500 ~320 MB. The matrix `npz` is a denser denormalized representation of the same data; once it exists the per-record JSON's only remaining use is per-(bus, ts) auditing.

**Default: gzip the per-record outputs.** Stage writers open via `gzip.open()` and the extension becomes `.json.gz`. Compression ratio is ~10×, so 70 MB → ~7 MB and 320 MB → ~32 MB. Inspection is unchanged: `zcat`, `gunzip -c`, and `pd.read_json("path.json.gz")` all work natively. Summary JSONs (`matrix_summary.json`, `clustering/summary.json`) stay uncompressed — they're already tiny and you want them grep-able.

**Override flag** at both the orchestrator and per-stage level:

| `--records-output` value | Behavior |
|---|---|
| `gz` (default) | Per-record outputs written as `.json.gz`. Matrix stage reads either `.json` or `.json.gz` transparently. |
| `json` | Per-record outputs uncompressed (current behavior). For ad-hoc debugging or pre-existing tooling that expects `.json`. |
| `none` | Per-record outputs are still written (matrix stage needs them) but the orchestrator deletes them after matrix exits `ok`. For very large runs where the audit value is low. |

This shape gives a sensible default that handles the scale-up curve, a one-flag escape hatch for either direction, and no upstream API changes for callers who just want things to work.

### 5. New orchestrator: `compute/run_pipeline.py`

Single composition layer. CLI:

```
python -m compute.run_pipeline \
    --run-id <name> \
    --dates-file compute/sample_specs/reference_dates.json \
    [--ref-methods hub_avg,system_lambda_kkt,...] \
    [--algos hierarchical_corr,kmeans_vec,pca_kmeans] \
    [--ks 4,6,8,10,12,16] \
    [--records-output {gz,json,none}]   # default gz — see §4
    [--skip-completed]                  # default true — skip stages whose outputs exist
    [--force]                           # rerun everything
```

Behavior:
- Creates `runs/<run_id>/` if missing; writes `meta.json` with start time, git sha, dates-file SHA-256, per-stage `status` and `elapsed_s`.
- Copies the dates file into the run directory.
- Asserts every timestamp in the dates file has a corresponding `bus_snapshots` row in Postgres before running congestion. If missing, prints the list and the suggested `write_snapshots.py --start --end` command — does **not** auto-ingest (different blast radius; user gates that).
- Runs each stage in sequence via subprocess of the first-class CLI scripts (cheaper than refactoring them into importable libraries this sprint). Skips a stage if `--skip-completed` and its output file exists. On failure: writes the traceback into `meta.json` and stops.
- If `--records-output none`: after the matrix stage exits `ok`, deletes `runs/<run_id>/congestion/{model_results,ercot_results}.json*` (the per-record outputs were already consumed; the npz carries forward).
- Final line: print run directory and one-line size summary.

### 6. Sample expansion: 120 snapshots (30 per regime)

`compute/sample_specs/extract_dates.py` already does regime-balanced sampling. Bump per-regime target to 30 (4 regimes × 30 = 120) and write `compute/sample_specs/reference_dates_120.json`. Expected footprint per run with default `.json.gz`: ~7 MB compressed per-record JSON, ~10 MB npz, ~3–5 MB clustering artifacts (~20 MB total). Total runtime: congestion ~3–4 min, matrix ~30 s, clustering sweep (4 ref × 5 algos × 6 Ks = 120 cells) ~5–8 min. Under the 10-minute clustering budget from the 0020 acceptance criterion.

### 7. Housekeeping

- `compute/runs/` → `.gitignore`.
- `compute/runs/README.md` documenting the per-run subdir layout (one paragraph + the tree from §2).
- `compute/README.md` updated: "Running the pipeline" section pointing at `run_pipeline.py` as canonical; per-stage scripts moved to "Debugging individual stages".
- The five loose untracked artifacts in `compute/experiments/congestion_calculation/` (from git status) move to `compute/runs/legacy-test-persist/` and `legacy-final-merit/`. Delete the `final-merit` set if not needed for comparison.

## Decomposition into branches

Six branches, each independently mergeable and leaving the codebase in a working state. Branches gate on the prior one. The three mechanical lifts (congestion, clustering, sample-specs) are folded into one branch as separate commits — they share a single concern (§1) and a single round of import-rewrite review. Total estimated diff: ~800 LOC (most of it file moves and import updates).

### Branch 1 — `chore/runs-layout` *(§2, §7)*
Establish the artifact convention without touching compute logic.
- Add `compute/runs/` to `.gitignore`.
- Move the five untracked artifacts in `compute/experiments/congestion_calculation/` into `compute/runs/legacy-test-persist/{congestion,matrix}/` and `compute/runs/legacy-final-merit/` (or delete `final-merit` set).
- Migrate `compute/experiments/zonal_clustering/runs/test-persist/` to `compute/runs/legacy-test-persist/clustering/`.
- Add `compute/runs/README.md`.

**Working state:** existing stage scripts still resolve via explicit-path flags pointed at the new artifact locations.

### Branch 2 — `refactor/lift-to-compute` *(§1)*
Mechanical file moves + renames; no behavior change. Use `git mv` so rename detection preserves blame. Three commits, each independently re-runnable against the 11-snapshot replay:

**2a — lift congestion**
- Add `compute/__init__.py` and `compute/congestion/__init__.py`.
- `git mv experiments/congestion_calculation/congestion.py compute/congestion/compute.py`
- `git mv experiments/congestion_calculation/system_lambda_estimators.py compute/congestion/system_lambda_estimators.py`
- `git mv experiments/congestion_calculation/congestion_snapshot.py compute/congestion/snapshot_runner.py`
- `git mv experiments/congestion_calculation/ercot_congestion_snapshot.py compute/congestion/ercot_runner.py`
- `git mv experiments/congestion_calculation/congestion_matrix.py compute/matrix.py`
- Delete `experiments/congestion_calculation/` directory (now empty except for `__pycache__`).
- Drop `sys.path.insert(...)` hacks at the top of each moved script; rewrite imports as package-style (`from compute.snapshot import compute_snapshot_batch`, `from .compute import compute_congestion` within the package, `from compute.congestion.compute import compute_congestion` from outside).
- Update any external references (Phase 3 plan docs, READMEs) to the new paths and module names.
- Smoke: 11-snapshot reference replay (`python -m compute.congestion.snapshot_runner --dates-file …`, then `python -m compute.matrix --model-results …`) produces identical outputs to pre-lift artifacts in `compute/runs/legacy-test-persist/`.

**2b — lift clustering**
- Add `compute/clustering/__init__.py`.
- `git mv experiments/zonal_clustering/clustering.py compute/clustering/algorithm.py`
- `git mv experiments/zonal_clustering/diagnostics.py compute/clustering/diagnostics.py`
- `git mv experiments/zonal_clustering/polygons.py compute/clustering/polygons.py`
- `git mv experiments/zonal_clustering/select_zones.py compute/clustering/select_zones.py`
- `git mv experiments/zonal_clustering/run_clustering.py compute/clustering/runner.py`
- `git mv experiments/zonal_clustering/tests compute/clustering/tests`
- Delete `experiments/zonal_clustering/`.
- Rewrite imports: existing `from experiments.zonal_clustering.clustering import ...` becomes `from compute.clustering.algorithm import ...` (or relative `from .algorithm import ...` within the package).
- Smoke: clustering sweep on 2a's matrix output reproduces the legacy clustering artifacts.

**2c — relocate sample specs**
- Delete `compute/profiling/reference_snapshot.py` and `compute/profiling/reference_snapshots.json` (dead; superseded by `compute/test_snapshot.py`).
- Add `compute/sample_specs/__init__.py`.
- `git mv compute/profiling/extract_sample_snapshot_dates.py compute/sample_specs/extract_dates.py`
- `git mv compute/profiling/reference_dates.json compute/sample_specs/reference_dates.json`
- Remove the now-empty `compute/profiling/` directory.
- Update the 7 active references to `/compute/profiling/reference_dates.json`:
  - `compute/congestion/snapshot_runner.py` (`DEFAULT_DATES_FILE` constant + docstring).
  - `compute/congestion/ercot_runner.py` (same).
  - `compute/experiments/zonal_load/compare_zonal_lmp/compare_zonal_lmp.py` (`REF_DATES` constant).
  - `compute/experiments/zonal_load/cap_sweep/cap_sweep.py` (same).
  - `compute/experiments/zonal_load/line_expansion_candidates/far_west_candidates.py` (same).
  - `compute/experiments/zonal_load/permian_backbone/pilot_backbone.py` (same).
  - `compute/experiments/zonal_load/feasibility_diagnosis/diagnose_zonal_infeasibility.py` (same).
- Grep audit: `grep -rn "profiling" compute/` returns zero hits.
- Smoke: all callers find the dates file at the new path; 11-snapshot reference replay still reproduces.

**Working state:** all production-grade modules live under first-class `compute/` packages; experiments/zonal_load/* updated to point at the new dates path; experiments/ now holds only genuinely exploratory work.

### Branch 3 — `feat/stage-run-ids` *(§3, §4)*
Add `--run-id` to each stage CLI and switch per-record writers to gzip default. Five commits — one per script, plus the gzip writer change:
- 3a — Per-record writers in `compute/congestion/snapshot_runner.py` and `ercot_runner.py` open via `gzip.open()` when output extension is `.json.gz`; matrix loader in `compute/matrix.py` transparently handles either `.json` or `.json.gz`. Adds `--records-output {gz,json}` flag (default `gz`).
- 3b — `compute/congestion/snapshot_runner.py --run-id` defaults outputs to `runs/<run_id>/congestion/model_results.json.gz`.
- 3c — `compute/congestion/ercot_runner.py --run-id` defaults to `runs/<run_id>/congestion/ercot_results.json.gz`.
- 3d — `compute/matrix.py --run-id` derives `--model-results` from `runs/<run_id>/congestion/model_results.json[.gz]`, writes to `runs/<run_id>/matrix/`.
- 3e — `compute/clustering/runner.py --run-id` derives `--matrices` and `--out-dir`; inner `runs/<name>/` nesting removed.

Each commit's smoke: chain to the previous commit's output via `--run-id repro-11`.

**Working state:** each stage usable both ways (explicit flags or `--run-id`). Existing scripts that hard-code paths are unbroken.

### Branch 4 — `feat/pipeline-orchestrator` *(§5, §4)*
Add `compute/run_pipeline.py`. Pure composition; no further changes to stage scripts.
- Subprocess composition via `python -m compute.congestion.snapshot_runner`, `python -m compute.congestion.ercot_runner`, `python -m compute.matrix`, `python -m compute.clustering.runner`.
- `meta.json` with run_id, git sha, dates-file SHA-256, per-stage `status` and `elapsed_s`.
- Copies dates file into run dir.
- Missing-snapshot guard against `bus_snapshots` before launching congestion.
- `--skip-completed` (default true) and `--force` flags.
- `--records-output {gz,json,none}` propagated to congestion stage. When `none`: orchestrator deletes `runs/<run_id>/congestion/*.json*` after matrix stage exits `ok`.

**Verification:** orchestrator-on-11-snapshot replay produces a `runs/repro-test-persist/` tree whose npz matches `compute/runs/legacy-test-persist/matrix/congestion_matrices.npz`. Re-run is a no-op.

### Branch 5 — `feat/sample-expansion-120` *(§6)*
- `compute/sample_specs/extract_dates.py`: per-regime target → 30 (CLI flag, default 30).
- Generate `compute/sample_specs/reference_dates_120.json`. Commit the file.
- Run `python -m compute.run_pipeline --run-id v1-120 --dates-file compute/sample_specs/reference_dates_120.json`. Verify `meta.json` shows all stages `ok` and total wall < 15 min. Spot-check disk: per-record outputs ~7 MB compressed.

### Branch 6 — `docs/orchestrator-readme` *(§7)*
- Update `compute/README.md`: "Running the pipeline" section pointing at `run_pipeline.py` as canonical; per-stage scripts as "Debugging individual stages".
- Brief note in `plan/phase4-working-outline.md` (where this plan lives post-save) marking the integration sprint complete and pointing at the next sprint (Phase 4 validation).

---

## Critical files

Moved (with imports rewritten, sys.path hacks removed; via `git mv` for blame continuity):
- `compute/experiments/congestion_calculation/congestion.py` → `compute/congestion/compute.py`.
- `compute/experiments/congestion_calculation/system_lambda_estimators.py` → `compute/congestion/system_lambda_estimators.py`.
- `compute/experiments/congestion_calculation/congestion_snapshot.py` → `compute/congestion/snapshot_runner.py`.
- `compute/experiments/congestion_calculation/ercot_congestion_snapshot.py` → `compute/congestion/ercot_runner.py`.
- `compute/experiments/congestion_calculation/congestion_matrix.py` → `compute/matrix.py`.
- `compute/experiments/zonal_clustering/clustering.py` → `compute/clustering/algorithm.py`.
- `compute/experiments/zonal_clustering/diagnostics.py` → `compute/clustering/diagnostics.py`.
- `compute/experiments/zonal_clustering/polygons.py` → `compute/clustering/polygons.py`.
- `compute/experiments/zonal_clustering/select_zones.py` → `compute/clustering/select_zones.py`.
- `compute/experiments/zonal_clustering/run_clustering.py` → `compute/clustering/runner.py`.
- `compute/experiments/zonal_clustering/tests/` → `compute/clustering/tests/`.
- `compute/profiling/extract_sample_snapshot_dates.py` → `compute/sample_specs/extract_dates.py`.
- `compute/profiling/reference_dates.json` → `compute/sample_specs/reference_dates.json`.

Deleted:
- `compute/profiling/reference_snapshot.py`, `compute/profiling/reference_snapshots.json` (dead).
- `compute/profiling/` directory (after moves).
- `compute/experiments/congestion_calculation/` directory (after moves).
- `compute/experiments/zonal_clustering/` directory (after moves).

Modified (imports + path references):
- `compute/experiments/zonal_load/{compare_zonal_lmp,cap_sweep,line_expansion_candidates,permian_backbone,feasibility_diagnosis}/*.py` — `REF_DATES` constant.
- `compute/README.md`, `.gitignore`.
- Phase 3 plan docs (`plan/phase3-decomposition.md`) and any other path-referencing docs.

New:
- `compute/__init__.py`, `compute/congestion/__init__.py`, `compute/clustering/__init__.py`, `compute/sample_specs/__init__.py`.
- `compute/run_pipeline.py`.
- `compute/runs/README.md`.
- `compute/sample_specs/reference_dates_120.json` (generated; committed).

Preserved untouched:
- `compute/write_snapshots.py`, `compute/test_snapshot.py`, `compute/snapshot.py`, all other top-level `compute/*.py`.

## Verification

1. **Per-branch smoke (Branches 1–2):** each commit of the lift branch reproduces the existing 11-snapshot artifacts using its newly-located scripts. Diff against `compute/runs/legacy-test-persist/` is empty (modulo gzip wrapping introduced in Branch 3).
2. **Stage-by-stage `--run-id` (Branch 3):** running each stage with `--run-id repro-11` lands artifacts in `runs/repro-11/<stage>/`; per-record outputs default to `.json.gz`; matrix transparently reads both `.json` and `.json.gz`; explicit-path flags still work.
3. **Orchestrator 11-snapshot replay (Branch 4):** `python -m compute.run_pipeline --run-id repro-test-persist --dates-file compute/sample_specs/reference_dates.json` produces a tree whose npz round-trips against `compute/runs/legacy-test-persist/matrix/congestion_matrices.npz` (matrix shapes + per-ref non-null masks match).
4. **Skip-completed semantics (Branch 4):** re-running the orchestrator with the same `--run-id` is a no-op (each stage prints `skip: <stage> already complete`), runs in under 2 s. `--force` reruns everything.
5. **Missing-snapshot guard (Branch 4):** dates file containing a timestamp absent from `bus_snapshots` → orchestrator prints the missing timestamp and exits non-zero without launching congestion.
6. **Records-output modes (Branch 4):** running with `--records-output json` produces uncompressed `.json` files; with `--records-output none` the per-record files are deleted after matrix completes (verified by `ls runs/<run_id>/congestion/`).
7. **Full 120-snapshot validation run (Branch 5):** `python -m compute.run_pipeline --run-id v1-120 --dates-file compute/sample_specs/reference_dates_120.json` completes end-to-end. `meta.json` shows all stages `ok`, total wall < 15 min. Clustering summary loads into a pandas DataFrame with the expected columns. Spot-check: one (ref, algo, K) cell's GeoJSON renders in `geopandas` and labels look spatially coherent. `du -sh runs/v1-120/congestion/` ≤ 10 MB.
8. **Sprawl check:** `du -sh compute/runs/v1-120/` ≤ 25 MB; `compute/congestion/`, `compute/clustering/`, and the residual `compute/experiments/` contain no new loose artifacts.
9. **Untouched-paths check:** `git log --oneline compute/write_snapshots.py compute/test_snapshot.py compute/snapshot.py` shows no commits from this sprint.

## Out of scope (deferred)

- **Integrating into `write_snapshots.py`.** The eventual goal — `write_snapshots` triggers congestion + matrix + clustering inline. Different sprint. This sprint only ensures the orchestrator stands on its own first.
- **Phase 4 validation framework** (Tier 1–5 metrics) — next sprint, will consume `runs/<run_id>/` as input.
- **Selecting the final reference method or zone count** — output of Phase 4, not this sprint.
- **Backfilling missing snapshot ingestion.** The orchestrator detects gaps; filling them stays a manual `write_snapshots.py` action.
- **Refactoring stage scripts into purely importable libraries.** Subprocess composition is fine for now.
- **Pruning dormant `experiments/zonal_load/*` scripts.** They're updated to point at the new dates path; deletion is a separate concern.
- **Cloud/remote runs, scheduled runs, or UI.**
