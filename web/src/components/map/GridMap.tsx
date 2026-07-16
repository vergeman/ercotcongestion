import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { SpRow, ViewMode } from "../../api/types";
import {
  lmpColor,
  normalizeLmpFromStats,
  modeledCongestionColor,
  normalizeModeledCongestion,
  type LmpStats,
  type ModeledCongestionStats,
} from "../../lib/colors";

// Major ERCOT-region cities, for map orientation only. Rendered as a faint
// symbol layer beneath the data layers — no basemap, keeps the dark canvas.
const CITY_LABELS: GeoJSON.FeatureCollection<GeoJSON.Point> = {
  type: "FeatureCollection",
  features: (
    [
      ["Houston", -95.37, 29.76],
      ["Dallas", -96.8, 32.78],
      ["Fort Worth", -97.33, 32.75],
      ["San Antonio", -98.49, 29.42],
      ["Austin", -97.74, 30.27],
      ["Corpus Christi", -97.4, 27.8],
      ["Laredo", -99.51, 27.51],
      ["Lubbock", -101.86, 33.58],
      ["Amarillo", -101.83, 35.22],
      ["Midland", -102.08, 31.99],
      ["Waco", -97.15, 31.55],
      ["McAllen", -98.23, 26.2],
      ["Abilene", -99.73, 32.45],
    ] as [string, number, number][]
  ).map(([name, lng, lat]) => ({
    type: "Feature",
    geometry: { type: "Point", coordinates: [lng, lat] },
    properties: { name },
  })),
};

interface Props {
  // settlement_points FeatureCollection from /topology. Features carry
  // `sp_id` (the promoteId) plus sp_type / load_zone / capacity_mw.
  points: unknown | null;
  rows: SpRow[];
  viewMode: ViewMode;
  lmpStats: LmpStats | null;
  mcStats: ModeledCongestionStats | null;
  onSpHover: (
    spId: string | null,
    props: Record<string, unknown> | null
  ) => void;
  onSpClick: (spId: string, props: Record<string, unknown>) => void;
  onMapClick: () => void;
  selectedSpId: string | null;
  // `side` names the pane so App can namespace per-side state; `onMapReady`
  // exposes the maplibre instance so App can mirror the camera across panes.
  side?: "prediction" | "actual";
  onMapReady?: (map: maplibregl.Map) => void;
}

export default function GridMap({
  points,
  rows,
  viewMode,
  lmpStats,
  mcStats,
  onSpHover,
  onSpClick,
  onMapClick,
  selectedSpId,
  onMapReady,
}: Props) {
  const prevSelectedRef = useRef<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  // Flipped inside the topology effect's onLoad handler after the `sps` source
  // is added. Coloring / selection effects gate on this so a remount doesn't
  // paint into a map whose source isn't ready yet — and re-fire the paint the
  // moment the source lands.
  const [sourcesReady, setSourcesReady] = useState(false);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const tooltipRef = useRef<maplibregl.Popup | null>(null);

  // Stash the latest callback props in a ref so the map setup effect can bind
  // handlers once on mount and still call the latest version of each callback.
  const callbacksRef = useRef({ onSpHover, onSpClick, onMapClick });
  useEffect(() => {
    callbacksRef.current = { onSpHover, onSpClick, onMapClick };
  }, [onSpHover, onSpClick, onMapClick]);

  // Initialize map once
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {},
        layers: [],
        glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
      },
      center: [-99.5, 31.5], // Texas center
      zoom: 5.5,
      minZoom: 4,
      maxZoom: 14,
      attributionControl: false,
    });

    map.addControl(
      new maplibregl.NavigationControl({ showCompass: false }),
      "bottom-right"
    );

    mapRef.current = map;
    onMapReady?.(map);
    tooltipRef.current = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      className: "grid-tooltip",
      offset: 8,
    });

    return () => {
      map.remove();
      mapRef.current = null;
      setSourcesReady(false);
    };
  }, []);

  // Load settlement points as a source + base layers
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !points) return;

    const fc = points as GeoJSON.FeatureCollection;

    const onLoad = () => {
      if (!map.getSource("sps")) {
        map.addSource("sps", {
          type: "geojson",
          data: fc,
          promoteId: "sp_id",
        });
      }

      // City orientation labels — added first so the SP circles draw on top.
      if (!map.getSource("cities")) {
        map.addSource("cities", { type: "geojson", data: CITY_LABELS });
      }
      if (!map.getLayer("city-labels")) {
        map.addLayer({
          id: "city-labels",
          type: "symbol",
          source: "cities",
          layout: {
            "text-field": ["get", "name"],
            "text-font": ["Noto Sans Regular"],
            "text-size": ["interpolate", ["linear"], ["zoom"], 4, 10, 8, 14],
            "text-anchor": "left",
            "text-offset": [0.6, 0],
            "text-letter-spacing": 0.08,
            "text-transform": "uppercase",
          },
          paint: {
            "text-color": "#5b6b7f",
            "text-halo-color": "#0a0d12",
            "text-halo-width": 1.2,
            "text-opacity": 0.75,
          },
        });
      }

      // SP circles, colored per viewMode via feature-state.
      if (!map.getLayer("sps")) {
        map.addLayer({
          id: "sps",
          type: "circle",
          source: "sps",
          paint: {
            "circle-color": [
              "case",
              ["!=", ["feature-state", "color"], null],
              ["feature-state", "color"],
              "#1a4731",
            ],
            "circle-opacity": 0.9,
            "circle-radius": [
              "interpolate",
              ["linear"],
              ["zoom"],
              4,
              2,
              8,
              4,
              12,
              7,
            ],
            "circle-stroke-width": [
              "case",
              ["boolean", ["feature-state", "selected"], false],
              3,
              ["boolean", ["feature-state", "hovered"], false],
              2,
              0,
            ],
            "circle-stroke-color": "#38bdf8",
          },
        });
      }

      // Hover interactions
      map.on("mousemove", "sps", (e) => {
        if (!e.features?.length) return;
        map.getCanvas().style.cursor = "crosshair";
        const props = e.features[0].properties as Record<string, unknown>;
        callbacksRef.current.onSpHover(props.sp_id as string, props);
        tooltipRef.current
          ?.setLngLat(e.lngLat)
          .setHTML(
            `<div class="tip-id">${props.sp_id}</div>
             <div class="tip-zone">${props.load_zone ?? "—"}</div>`
          )
          .addTo(map);
      });

      map.on("mouseleave", "sps", () => {
        map.getCanvas().style.cursor = "";
        callbacksRef.current.onSpHover(null, null);
        tooltipRef.current?.remove();
      });

      map.on("click", "sps", (e) => {
        if (!e.features?.length) return;
        e.preventDefault?.();
        const props = e.features[0].properties as Record<string, unknown>;
        callbacksRef.current.onSpClick(props.sp_id as string, props);
      });

      // Sources are live — coloring/selection effects can now paint.
      setSourcesReady(true);
    };

    // Click on empty map → clear pinned
    map.on("click", (e) => {
      if (e.defaultPrevented) return;
      callbacksRef.current.onMapClick();
    });

    if (map.isStyleLoaded()) {
      onLoad();
    } else {
      map.once("load", onLoad);
    }
  }, [points]);

  // Color SPs when rows/viewMode/stats change. Same $/MWh quantity → same
  // color mapping on both panes, so prediction and actual are comparable by
  // eye. With no rows loaded, clear the color feature-state so the circles
  // fall back to the base fill.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource("sps")) return;

    if (!rows.length) {
      if (!points) return;
      const fc = points as GeoJSON.FeatureCollection<
        GeoJSON.Point,
        { sp_id: string }
      >;
      for (const feat of fc.features) {
        map.removeFeatureState(
          { source: "sps", id: feat.properties.sp_id },
          "color"
        );
      }
      return;
    }

    for (const row of rows) {
      let color: string;
      if (viewMode === "congestion") {
        color = mcStats
          ? modeledCongestionColor(
              normalizeModeledCongestion(row.congestion, mcStats)
            )
          : modeledCongestionColor(0);
      } else {
        color = lmpStats
          ? lmpColor(normalizeLmpFromStats(row.spp, lmpStats))
          : lmpColor(0.5);
      }
      map.setFeatureState({ source: "sps", id: row.sp_id }, { color });
    }
  }, [rows, viewMode, lmpStats, mcStats, points, sourcesReady]);

  // Selected SP
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource("sps")) return;
    if (prevSelectedRef.current && prevSelectedRef.current !== selectedSpId) {
      map.setFeatureState(
        { source: "sps", id: prevSelectedRef.current },
        { selected: false }
      );
    }
    if (selectedSpId) {
      map.setFeatureState(
        { source: "sps", id: selectedSpId },
        { selected: true }
      );
    }
    prevSelectedRef.current = selectedSpId;
  }, [selectedSpId, sourcesReady]);

  return (
    <>
      <div ref={containerRef} style={{ width: "100%", height: "100%" }} />
      <style>{`
        .maplibregl-ctrl-group {
          background: #0f1217 !important;
          border: 1px solid #252d3a !important;
        }
        .maplibregl-ctrl-group button {
          background: transparent !important;
          border: none !important;
          padding: 0 !important;
        }
        .maplibregl-ctrl-zoom-in .maplibregl-ctrl-icon,
        .maplibregl-ctrl-zoom-out .maplibregl-ctrl-icon {
          filter: invert(1) opacity(0.6);
        }
        .grid-tooltip .maplibregl-popup-content {
          background: #0f1217;
          border: 1px solid #252d3a;
          border-radius: 4px;
          padding: 6px 10px;
          color: #e2e8f0;
          font-family: 'Space Mono', monospace;
          font-size: 11px;
          pointer-events: none;
        }
        .grid-tooltip .maplibregl-popup-tip { display: none; }
        .tip-id { color: #38bdf8; font-size: 11px; }
        .tip-zone { color: #8899aa; font-size: 10px; margin-top: 2px; }
      `}</style>
    </>
  );
}
