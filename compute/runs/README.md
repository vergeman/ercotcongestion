# compute/runs/

Canonical artifact tree for pipeline outputs. One subdirectory per `run_id`. The
directory itself is gitignored (only this README is tracked) — runs are local
working state, not source.

Each run owns a self-contained set of artifacts keyed by `<run_id>`, with stage
subdirs that mirror the source package names (`congestion`, `matrix`,
`clustering`). A run produced by the orchestrator (`compute/run_pipeline.py`)
also carries `meta.json` (provenance: git sha, dates-file SHA-256, per-stage
status + elapsed) and a copy of the dates file it consumed.

```
compute/runs/<run_id>/
  meta.json                       # orchestrator provenance
                                  # (run_id, created_at, dates-file SHA-256, git sha, per-stage status/elapsed_s)

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
