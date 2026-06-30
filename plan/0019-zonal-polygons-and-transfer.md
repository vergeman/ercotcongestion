# 0019 - zonal-polygons-and-transfer

Type: feat
Branch: feat/zonal-clustering

## Context

* 0017/0018 ship clustering + diagnostics as pure functions on bus×hour matrices. 0020 needs to (a) turn model-side labels into polygons, (b) transfer those polygons to ERCOT settlement points, and (c) emit GeoJSON for the map layer.
* Polygons and point-in-polygon transfer share `geopandas` machinery, the same `(labels, coords)` input shape, and the same singleton/fallback edge cases — bundle them.
* `preprocess/assign_bus_weather_load_zones.py::assign_zone` already does point-in-polygon-with-nearest-fallback for the weather-zone case; reuse if importable, else mirror the pattern.

## Goal

* Ship `compute/experiments/zonal_clustering/polygons.py` with `build_polygons`, `transfer_labels`, and `write_zones_geojson`.
* Each function callable in isolation from a REPL given `(labels, coords)` and (for transfer) a polygons `GeoDataFrame`.
* Add tests confirming polygons round-trip through GeoJSON and label transfer recovers > 95% of planted labels on perturbed coords.

## Approach

* Work in: `compute/experiments/zonal_clustering/polygons.py` (new module in the existing 0017/0018 package).
* Functions:
  * `build_polygons(labels: pd.Series, coords: pd.DataFrame, alpha: float | None = None) -> gpd.GeoDataFrame` — group `coords[['lat','lon']]` by `labels` (drop `-1`); for each cluster build an alpha-shape via `shapely.concave_hull` (when `alpha` given) with `convex_hull` fallback when `concave_hull` fails or returns an invalid geometry; clusters with < 3 points are logged and dropped. Output columns: `[cluster_id, n_buses, centroid_lat, centroid_lon, geometry]`, CRS = `EPSG:4326`.
  * `transfer_labels(polygons: gpd.GeoDataFrame, target_coords: pd.DataFrame) -> pd.Series` — build a points `GeoDataFrame` from `target_coords[['lat','lon']]`, `gpd.sjoin(..., predicate='within')` against `polygons`, drop dup indices keeping first, and for unmatched points fall back to nearest polygon centroid in `EPSG:3083` (Texas Albers). Return `pd.Series[target_coords.index -> cluster_id]`, dtype int, named `cluster_id`. Mirror the structure of `assign_zone`; import it only if signature fits cleanly, otherwise re-implement (it expects a `zone_col` string, which doesn't map here).
  * `write_zones_geojson(polygons: gpd.GeoDataFrame, path: str | Path) -> None` — `polygons.to_file(path, driver='GeoJSON')`. Properties = the non-geometry columns from `build_polygons`.
* Reuse: `build_bus_gdf` pattern from `preprocess/assign_bus_weather_load_zones.py` for points-from-lat-lon (don't import — it takes a PyPSA network; mirror the `gpd.points_from_xy` line). `concave_hull` lives in `shapely.ops` (shapely ≥ 2.0); confirm version before writing.
* Tests: `compute/experiments/zonal_clustering/tests/test_polygons.py`. Add a `coords` fixture to `conftest.py` (jittered lat/lon around 3 per-cluster centroids, matching the existing 50-bus planted fixture) if not already present from 0018. Assertions:
  * `build_polygons(true_labels, coords)` returns 3 rows, no singletons, all geometries valid (`gdf.is_valid.all()`).
  * `transfer_labels(polygons, coords + small_jitter)` recovers > 95% of `true_labels`.
  * GeoJSON round-trips: `write_zones_geojson(p, tmp_path)` → `gpd.read_file(tmp_path)` produces a frame with the same `cluster_id` set and identical geometries (within tolerance).
  * Singleton handling: forge a fourth cluster with 2 buses; assert it's dropped and a warning is logged.
* Do NOT touch: `clustering.py`, `diagnostics.py`, the 0016 npz, the sweep CLI, or any file under `congestion_calculation/` or `preprocess/`. No (ref, algo, K) loop — that's 0020.

## Status

Implemented. `geopandas==1.1.4` and `shapely==2.1.2` already present in the compute image as pypsa transitive deps; no Dockerfile change needed. 5/5 polygon tests pass, 25/25 zonal_clustering suite green (`docker compose run --rm compute python -m pytest /compute/experiments/zonal_clustering/tests/ -v`, 2.43s).

## Acceptance

* [x] `from experiments.zonal_clustering.polygons import build_polygons, transfer_labels, write_zones_geojson` succeeds.
* [x] `build_polygons` on the 50-bus planted fixture returns a `GeoDataFrame` of 3 valid polygons with the documented columns and `EPSG:4326` CRS.
* [x] `transfer_labels(polygons, jittered_coords)` recovers > 95% of original labels on the same fixture.
* [x] Clusters with < 3 points are dropped with a log line, not raised on.
* [x] GeoJSON written by `write_zones_geojson` round-trips through `gpd.read_file` with matching `cluster_id` set and equal geometries.
* [x] `pytest compute/experiments/zonal_clustering/tests/test_polygons.py` passes (5/5).
* [x] No file I/O in `build_polygons` or `transfer_labels`; only `write_zones_geojson` touches disk.
