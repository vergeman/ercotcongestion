# CM.4 — retire-geo-transfer

Type: refactor
Branch: refactor/cm.4-retire-geo-transfer

## Goal

* Remove `transfer_labels` from the clustering sweep path so `_run_cell` no longer emits `ercot_sp_labels_*.csv`, `sil_ercot`, or `sc_ercot`.
* Keep `transfer_labels` callable, but only for a one-shot geo-vs-behavioral disagreement diagnostic.
* Add `compute/mapping/diagnostics.py` with a geo-vs-CM.1-best-bus disagreement report.

## Context

* D2 pivot: geographic containment is no longer the translation mechanism from model buses to ERCOT SPs — correlation/basis regression (CM.1/CM.2) replaces it. See [[01-correlation-map]].
* Sweep currently emits ERCOT-side artifacts and ERCOT-side ranking scores; these become misleading under the new paradigm.
* Must preserve callability of `transfer_labels` for the diagnostic — do not delete the function.

## Approach

* Work in: `compute/clustering/runner.py`, `compute/clustering/polygons.py`, `compute/clustering/select_zones.py` (only to drop refs to removed metrics), `compute/mapping/diagnostics.py` (new).
* In `runner._run_cell`: stop calling `transfer_labels`; stop writing `ercot_sp_labels_*.csv`; stop computing `sil_ercot`/`sc_ercot`. Update per-cell result dict accordingly.
* In `polygons.py`: keep `transfer_labels` importable and functional; add module docstring noting it's diagnostic-only now.
* In `compute/mapping/diagnostics.py`: implement `geo_vs_behavioral_disagreement(run_id)`:
  - Load CM.1 output (`mapping_correlation_<run_id>.npz`) — SP → best_bus (behavioral).
  - Load a representative geographic transfer result (invoke `transfer_labels` once against a chosen partition, or reuse most recent sweep artifact — spec first available).
  - Report per-SP disagreement (behavioral cluster of best_bus vs geo-assigned cluster) and top-line disagreement rate.
  - Output: `runs/<run_id>/mapping/geo_vs_behavioral_<run_id>.json` + optional npz of per-SP records.
* Do NOT touch: `compute/matrix.py`, mapping modules (CM.1–CM.3), select_zones scoring logic beyond removing dead metric refs (that lives in CM.6, [[06-ranking-demotion]]).

## Sections (commits)

### C1 — strip transfer_labels from sweep path

* Edit `runner._run_cell` to remove `transfer_labels` call, `sil_ercot`/`sc_ercot`, and CSV emission.
* Remove `sil_ercot`/`sc_ercot` from per-cell result dict; update any downstream reader that just iterates keys (defer scoring changes to CM.6).
* Update tests under `compute/clustering/tests/` that assert ERCOT outputs — drop or invert the assertions.
* Verify: a small sweep on v1-120 produces no `ercot_sp_labels_*.csv` and no `sil_ercot` in result dicts.

### C2 — add mapping diagnostics module

* Create `compute/mapping/diagnostics.py::geo_vs_behavioral_disagreement(run_id, partition_path)`.
* CLI: `python -m compute.mapping.diagnostics --run-id v1-120 --partition <path-to-cluster-labels>`.
* Load CM.1 correlation map; for each SP, compare geo-assigned cluster to behavioral cluster (cluster of best_bus).
* Write JSON summary (`disagreement_rate`, `n_sp`, `partition_id`) and per-SP npz.
* Verify: JSON exists with sane disagreement rate on v1-120.

## Acceptance

* [x] Sweep produces no `ercot_sp_labels_*.csv` files under `runs/<run_id>/clustering/`.
* [x] `sil_ercot` and `sc_ercot` no longer present in per-cell result dicts.
* [x] `transfer_labels` still importable and callable from `compute/clustering/polygons.py`.
* [x] `compute/mapping/diagnostics.py` produces a disagreement JSON on v1-120.
* [x] Existing clustering tests updated; suite passes.
