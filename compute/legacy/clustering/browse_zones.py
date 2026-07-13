"""Bulk-preview every derived-zone GeoJSON in a run as toggleable Folium layers.

Point at a run's clustering directory and get one HTML file where each
`zones_<ref>_<algo>_k<K>.geojson` becomes a checkbox-toggled overlay,
categorically colored by `cluster_id`. Intended for the Phase 3B selection
step where 100+ candidate partitions need eyeballing before picking one.

Usage::

    python -m compute.legacy.clustering.browse_zones \
        --run-dir compute/runs/v1-120 \
        [--pattern "zones_*_hybrid_geo_k*.geojson"] \
        [--output clusters.html]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import folium
import geopandas as gpd


DEFAULT_PATTERN = "zones_*.geojson"
DEFAULT_OUTPUT = Path("clusters.html")
TEXAS_CENTER = (31.5, -99.5)


def _style_fn(feature: dict) -> dict:
    cid = int(feature["properties"].get("cluster_id", 0))
    # Deterministic hue-cycle keeps neighboring cluster_ids visually distinct
    # without pulling in a colormap dep.
    hue = (cid * 47) % 360
    return {
        "fillColor": f"hsl({hue}, 70%, 50%)",
        "color": "#333",
        "weight": 1,
        "fillOpacity": 0.35,
    }


def build_map(files: list[Path]) -> folium.Map:
    m = folium.Map(location=list(TEXAS_CENTER), zoom_start=6, tiles="cartodbpositron")
    for gj in files:
        name = gj.stem.replace("zones_", "")
        gdf = gpd.read_file(gj)
        folium.GeoJson(
            gdf,
            name=name,
            style_function=_style_fn,
            tooltip=folium.GeoJsonTooltip(fields=["cluster_id", "n_buses"]),
            show=False,
        ).add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    return m


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--run-dir", required=True, type=Path,
                   help="Run directory (e.g. compute/runs/v1-120). "
                        "Zones read from <run-dir>/clustering/.")
    p.add_argument("--pattern", default=DEFAULT_PATTERN,
                   help=f"Glob against clustering/. Default: {DEFAULT_PATTERN}.")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                   help=f"Output HTML path. Default: {DEFAULT_OUTPUT}.")
    args = p.parse_args(argv)

    cluster_dir = args.run_dir / "clustering"
    if not cluster_dir.is_dir():
        print(f"not a directory: {cluster_dir}", file=sys.stderr)
        return 2

    files = sorted(cluster_dir.glob(args.pattern))
    if not files:
        print(f"no matches for {args.pattern} in {cluster_dir}", file=sys.stderr)
        return 3

    print(f"loading {len(files)} geojson layer(s) from {cluster_dir}")
    m = build_map(files)
    m.save(str(args.output))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
