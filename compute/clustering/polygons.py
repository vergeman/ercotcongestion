"""Polygon construction and label transfer for derived zonal clusters.

Under CM.5 polygons are a rendering choice, not a sweep artifact —
`build_polygons` is a pure function called on demand by
`compute.clustering.render_partition` for a chosen `(ref, algo, K)`.

* `build_polygons(labels, coords, alpha, out_path=None)` — convex (or
  concave-hull) polygons per cluster from `(lat, lon)`. Pure unless
  `out_path` is given, in which case a GeoJSON is also written.
* `transfer_labels(polygons, target_coords)` — point-in-polygon assignment
  with nearest-centroid fallback for points outside all polygons.
  DIAGNOSTIC-ONLY under the CM.1/CM.2 paradigm: the sweep no longer calls
  this, and geographic containment is not the model→ERCOT translation
  mechanism. Kept importable for one-shot geo-vs-behavioral disagreement
  reports (see `compute.mapping.diagnostics`).
* `write_zones_geojson(polygons, path)` — disk emission helper.

CRS convention: input lat/lon are EPSG:4326. Nearest-fallback distance is
computed in EPSG:3083 (Texas Albers) so the metric is meters.
"""
from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import concave_hull
from shapely.geometry import MultiPoint

log = logging.getLogger(__name__)

CRS_LATLON = "EPSG:4326"
CRS_METRIC = "EPSG:3083"  # Texas Albers


def _points_gdf(coords: pd.DataFrame) -> gpd.GeoDataFrame:
    """Build a points GeoDataFrame from a DataFrame with `lat`, `lon` cols."""
    return gpd.GeoDataFrame(
        coords[["lat", "lon"]].copy(),
        geometry=gpd.points_from_xy(coords["lon"], coords["lat"]),
        crs=CRS_LATLON,
    )


def build_polygons(
    labels: pd.Series,
    coords: pd.DataFrame,
    alpha: float | None = None,
    out_path: str | Path | None = None,
) -> gpd.GeoDataFrame:
    """One polygon per cluster from member `(lat, lon)` points.

    Clusters with `label == -1` are ignored. Clusters with < 3 points are
    logged and dropped (a polygon needs three points). When `alpha` is set,
    each polygon is the alpha-shape via `shapely.concave_hull`; on failure
    or invalid geometry we fall back to the convex hull.

    Returns a GeoDataFrame with columns
    `[cluster_id, n_buses, centroid_lat, centroid_lon, geometry]` in
    `EPSG:4326`. Pure by default — pass `out_path` to also write GeoJSON.
    """
    aligned = coords.reindex(labels.index)
    valid_mask = (labels != -1) & aligned[["lat", "lon"]].notna().all(axis=1)
    labels = labels[valid_mask]
    coords = aligned[valid_mask]

    rows = []
    for cid, idx in labels.groupby(labels).groups.items():
        pts = coords.loc[idx]
        if len(pts) < 3:
            log.info(
                "build_polygons: dropping cluster %s with %d points (<3)",
                cid, len(pts),
            )
            continue
        mp = MultiPoint(list(zip(pts["lon"].to_numpy(), pts["lat"].to_numpy())))
        geom = None
        if alpha is not None:
            try:
                cand = concave_hull(mp, ratio=alpha)
                if cand is not None and not cand.is_empty and cand.is_valid:
                    geom = cand
            except Exception as exc:
                log.info(
                    "build_polygons: concave_hull failed on cluster %s (%s);"
                    " falling back to convex hull",
                    cid, exc,
                )
        if geom is None:
            geom = mp.convex_hull
        rows.append({
            "cluster_id": int(cid),
            "n_buses": int(len(pts)),
            "centroid_lat": float(pts["lat"].mean()),
            "centroid_lon": float(pts["lon"].mean()),
            "geometry": geom,
        })

    polygons = gpd.GeoDataFrame(
        rows,
        columns=["cluster_id", "n_buses", "centroid_lat", "centroid_lon", "geometry"],
        geometry="geometry",
        crs=CRS_LATLON,
    )
    if out_path is not None and not polygons.empty:
        write_zones_geojson(polygons, out_path)
    return polygons


def transfer_labels(
    polygons: gpd.GeoDataFrame,
    target_coords: pd.DataFrame,
) -> pd.Series:
    """Assign each target point to a cluster via point-in-polygon, with
    nearest-centroid fallback for points outside every polygon.

    Returns a `pd.Series` indexed like `target_coords` with name `cluster_id`
    and `int` dtype. Mirrors `preprocess/assign_bus_weather_load_zones.py::
    assign_zone`'s sjoin-then-nearest pattern; not reused because that
    helper hard-codes a zone-name column.
    """
    if polygons.empty:
        return pd.Series(-1, index=target_coords.index, dtype=int, name="cluster_id")

    pts = _points_gdf(target_coords)
    joined = gpd.sjoin(
        pts,
        polygons[["cluster_id", "geometry"]],
        how="left",
        predicate="within",
    )
    if joined.index.has_duplicates:
        joined = joined[~joined.index.duplicated(keep="first")]

    unmatched = joined["cluster_id"].isna()
    if unmatched.any():
        log.info(
            "transfer_labels: %d/%d points outside all polygons — using nearest centroid",
            int(unmatched.sum()), len(joined),
        )
        centroids = gpd.GeoDataFrame(
            {"cluster_id": polygons["cluster_id"].to_numpy()},
            geometry=gpd.points_from_xy(
                polygons["centroid_lon"], polygons["centroid_lat"],
            ),
            crs=CRS_LATLON,
        ).to_crs(CRS_METRIC)
        pts_proj = pts.to_crs(CRS_METRIC)
        for idx in joined.index[unmatched]:
            d = centroids.distance(pts_proj.loc[idx, "geometry"])
            joined.loc[idx, "cluster_id"] = centroids.loc[d.idxmin(), "cluster_id"]

    return joined["cluster_id"].astype(int).rename("cluster_id")


def write_zones_geojson(polygons: gpd.GeoDataFrame, path: str | Path) -> None:
    """Write `polygons` to a GeoJSON file. Properties = all non-geometry columns."""
    polygons.to_file(str(path), driver="GeoJSON")
