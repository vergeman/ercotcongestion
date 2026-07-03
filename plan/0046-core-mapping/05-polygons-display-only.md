# CM.5 — polygons-display-only

Type: refactor
Branch: refactor/cm.5-polygons-display-only

## Goal

* Stop feeding polygons into clustering metrics; polygons become a rendering helper only.
* `build_polygons` invoked lazily for the chosen presentation partition, not per-cell during the sweep.
* Prefer point-tag output (`cluster_id` per point/bus) as the canonical partition artifact.

## Context

* D3 pivot: hulls are a presentation choice, not a validity signal. The mapping-first stack judges quality via CM.1/CM.2/CM.3, not spatial coherence of hulls.
* Rendering decision (hull vs point cluster vs voronoi) belongs in F2 (frontend / display selection), not in the compute sweep.
* Depends on transfer_labels removal from the sweep path being done first — see [[04-retire-geo-transfer]].

## Approach

* Work in: `compute/clustering/runner.py`, `compute/clustering/polygons.py`, `compute/clustering/select_zones.py` (only where it consumes polygon-derived scores).
* In `runner._run_cell`: remove polygon build and any spatial-coherence-from-polygon computation from the per-cell hot path. Persist point-tags: a `cluster_labels_<ref>_<algo>_k<K>.npz` (arrays `bus_id`, `cluster_id`) per cell.
* In `polygons.py`: keep `build_polygons` importable; make it a pure function that takes `(labels, bus_coords)` and returns GeoJSON (or a dict), with no side effects unless given an output path.
* Add a thin driver `compute/clustering/render_partition.py` (or a subcommand on `select_zones`) that materializes polygons only for a named `(algo, K)` chosen partition.
* Ensure `select_zones` no longer imports polygon-derived signals during ranking (leave the ranking-signal changes to CM.6 [[06-ranking-demotion]]; here we just ensure the ranking data flow does not require polygons).
* Do NOT touch: mapping modules, matrix builder, frontend rendering.

## Sections (commits)

### C1 — remove polygon build from sweep hot path

* Edit `runner._run_cell` to stop invoking polygon builders; write `cluster_labels_<ref>_<algo>_k<K>.npz` (arrays `bus_id`, `cluster_id`) instead.
* Delete polygon-writing side effects from the per-cell loop.
* Verify: a small sweep on v1-120 produces per-cell label npz files and zero GeoJSONs.

### C2 — polygons as render-only helper

* Refactor `polygons.build_polygons(labels, bus_coords) -> GeoJSON`; remove filesystem side effects unless `out_path` given.
* Add `compute/clustering/render_partition.py` with CLI: `--run-id --ref --algo --k --out geojson.json` that loads the corresponding labels npz and writes GeoJSON.
* Verify: `render_partition` produces a GeoJSON for a chosen `(algo, K)` on v1-120.

## Acceptance

* [ ] Sweep no longer writes GeoJSONs under `runs/<run_id>/clustering/` during `_run_cell`.
* [ ] Each cell writes a `cluster_labels_<ref>_<algo>_k<K>.npz` (arrays `bus_id`, `cluster_id`).
* [ ] `build_polygons` is a pure function; side effects only when caller requests output.
* [ ] `render_partition` CLI produces a GeoJSON for a named partition.
* [ ] `select_zones` ranking pipeline does not require polygon inputs.
