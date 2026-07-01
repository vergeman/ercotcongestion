import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { BusState, SnapshotMeta, ViewMode } from "../../api/types";
import { fetchPtdf } from "../../api/client";
import {
  lmpColor,
  normalizeLmpFromStats,
  modeledCongestionColor,
  normalizeModeledCongestion,
  bindingProximityColor,
  normalizeProximity,
  computeCongestionVsBasisRank,
  rankDeltaColor,
  type LmpStats,
  type ModeledCongestionStats,
} from "../../lib/colors";

// Track which bus IDs currently have a halo applied. Module-scoped so it
// survives across the effect's lifetimes — the map instance is too.
const activeHaloBusIds: Set<string> = new Set();

// Apply halo opacities + sign to a list of buses with their PTDF values.
// The strongest |PTDF| in the set scales to full opacity (~0.7); weaker
// ones fade proportionally (sub-linear so mid-range responders stay visible).
//
// Sign drives color via the bus-halos layer: positive PTDF → ice,
// negative PTDF → vibrant orange. This aligns with the diverging
// modeled_congestion palette (positive/import → warm; negative/export → cool),
// so hover-a-line reads in the same visual language as the underlying map.
// Operationally:
//   +PTDF: bus is "upstream" of the line. Reducing injection at this bus
//          (curtail gen, charge a battery) relieves the line.
//   −PTDF: bus is "downstream." Reducing load (DR) relieves the line.
const HALO_PEAK_OPACITY = 0.7;

function applyHalos(
  map: maplibregl.Map,
  buses: Array<{ bus_id: string; ptdf: number }>
): void {
  if (!map.getSource("buses")) return;
  // Find peak |PTDF| for normalization.
  let peak = 0;
  for (const b of buses) {
    const a = Math.abs(b.ptdf);
    if (a > peak) peak = a;
  }
  if (peak <= 0) return;

  for (const b of buses) {
    const norm = Math.sqrt(Math.abs(b.ptdf) / peak); // sub-linear
    const opacity = HALO_PEAK_OPACITY * Math.min(1, norm);
    map.setFeatureState(
      { source: "buses", id: b.bus_id },
      { halo_opacity: opacity, halo_sign: b.ptdf >= 0 ? 1 : -1 }
    );
    activeHaloBusIds.add(b.bus_id);
  }
}

function clearHalos(map: maplibregl.Map): void {
  if (!map.getSource("buses")) return;
  for (const id of activeHaloBusIds) {
    map.setFeatureState(
      { source: "buses", id },
      { halo_opacity: 0, halo_sign: 0 }
    );
  }
  activeHaloBusIds.clear();
}

interface Props {
  topology: unknown | null;
  buses: BusState[];
  meta: SnapshotMeta | null;
  viewMode: ViewMode;
  lmpStats: LmpStats | null;
  mcStats: ModeledCongestionStats | null;
  onBusHover: (
    busId: string | null,
    props: Record<string, unknown> | null
  ) => void;
  onLineHover: (
    lineId: string | null,
    props: Record<string, unknown> | null
  ) => void;
  onBusClick: (busId: string, props: Record<string, unknown>) => void;
  onLineClick: (lineId: string, props: Record<string, unknown>) => void;
  onMapClick: () => void;
  selectedBusId: string | null;
  selectedLineId: string | null;
}

export default function GridMap({
  topology,
  buses,
  meta,
  viewMode,
  lmpStats,
  mcStats,
  onBusHover,
  onLineHover,
  onBusClick,
  onLineClick,
  onMapClick,
  selectedBusId,
  selectedLineId,
}: Props) {
  const prevBindingRef = useRef<Set<string>>(new Set());
  const prevContingencyRef = useRef<Set<string>>(new Set());
  const prevSelectedBusRef = useRef<string | null>(null);
  const prevSelectedLineRef = useRef<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const metaRef = useRef<SnapshotMeta | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  // Track tooltip overlay
  const tooltipRef = useRef<maplibregl.Popup | null>(null);
  // PTDF halo state. We track the hovered line ID to avoid re-fetching on
  // mousemove repeats. The set of buses currently haloed lives at module
  // scope (see activeHaloBusIds above) so the helpers can clear surgically.
  const haloLineRef = useRef<string | null>(null);
  const haloDebounceRef = useRef<number | null>(null);

  // Stash the latest callback props in a ref so the map setup effect can
  // bind handlers once on mount and still call the latest version of each
  // callback. Without this, the effect would either need to re-run (and
  // re-create the map) every render, or it would silently call stale
  // callbacks. ESLint's exhaustive-deps rule was previously warning about
  // exactly this hazard.
  const callbacksRef = useRef({
    onBusHover,
    onLineHover,
    onBusClick,
    onLineClick,
    onMapClick,
  });
  useEffect(() => {
    callbacksRef.current = {
      onBusHover,
      onLineHover,
      onBusClick,
      onLineClick,
      onMapClick,
    };
  }, [onBusHover, onLineHover, onBusClick, onLineClick, onMapClick]);

  useEffect(() => {
    metaRef.current = meta;
  }, [meta]);

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
    tooltipRef.current = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      className: "grid-tooltip",
      offset: 8,
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Load topology as sources + base layers
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !topology) return;

    const topo = topology as { buses: object; lines: object };

    const onLoad = () => {
      if (!map.getSource("buses")) {
        map.addSource("buses", {
          type: "geojson",
          data: topo.buses as GeoJSON.FeatureCollection,
          promoteId: "bus_id",
        });
      }
      if (!map.getSource("lines")) {
        map.addSource("lines", {
          type: "geojson",
          data: topo.lines as GeoJSON.FeatureCollection,
          promoteId: "line_id",
        });
      }

      // Lines layer
      if (!map.getLayer("lines")) {
        map.addLayer({
          id: "lines",
          type: "line",
          source: "lines",
          paint: {
            "line-color": [
              "case",
              ["boolean", ["feature-state", "selected"], false],
              "#38bdf8",
              ["boolean", ["feature-state", "binding"], false],
              "#ec4899",
              ["boolean", ["feature-state", "contingency"], false],
              "#cbd5e1",
              "#1e2d3e",
            ],
            "line-width": [
              "interpolate",
              ["linear"],
              ["zoom"],
              4,
              [
                "case",
                ["boolean", ["feature-state", "selected"], false],
                2.5,
                ["boolean", ["feature-state", "binding"], false],
                2.0,
                ["boolean", ["feature-state", "contingency"], false],
                1.5,
                0.6,
              ],
              8,
              [
                "case",
                ["boolean", ["feature-state", "selected"], false],
                4.5,
                ["boolean", ["feature-state", "binding"], false],
                3.8,
                ["boolean", ["feature-state", "contingency"], false],
                2.8,
                1.2,
              ],
              12,
              [
                "case",
                ["boolean", ["feature-state", "selected"], false],
                6.5,
                ["boolean", ["feature-state", "binding"], false],
                6.0,
                ["boolean", ["feature-state", "contingency"], false],
                4.5,
                2.0,
              ],
            ],
            "line-dasharray": [
              "case",
              ["boolean", ["feature-state", "contingency"], false],
              ["literal", [2, 1.5]],
              ["literal", [1, 0]],
            ],
            "line-opacity": [
              "case",
              ["boolean", ["feature-state", "binding"], false],
              1.0,
              ["boolean", ["feature-state", "contingency"], false],
              0.85,
              0.5,
            ],
          },
        });
      }

      // Invisible thick layer for hover detection
      if (!map.getLayer("lines-hit")) {
        map.addLayer({
          id: "lines-hit",
          type: "line",
          source: "lines",
          paint: {
            "line-color": "#000",
            "line-opacity": 0, // invisible
            "line-width": 8, // wide hit area
          },
        });
      }

      // PTDF halo layer — rendered behind the bus circles. Opacity is set
      // via feature-state when a line is hovered, fading proportionally to
      // |PTDF|.
      if (!map.getLayer("bus-halos")) {
        map.addLayer({
          id: "bus-halos",
          type: "circle",
          source: "buses",
          paint: {
            "circle-radius": [
              "interpolate",
              ["linear"],
              ["zoom"],
              4,
              6,
              8,
              10,
              12,
              16,
            ],
            "circle-color": [
              "case",
              ["==", ["feature-state", "halo_sign"], -1],
              "#fb923c", // vibrant orange for -PTDF
              "#22d3ee", // ice for +PTDF
            ],
            "circle-opacity": [
              "case",
              ["!=", ["feature-state", "halo_opacity"], null],
              ["feature-state", "halo_opacity"],
              0,
            ],
            "circle-stroke-width": 0,
            "circle-blur": 0.5,
          },
        });
      }

      // Buses layer (circles, colored per viewMode via feature-state)
      if (!map.getLayer("buses")) {
        map.addLayer({
          id: "buses",
          type: "circle",
          source: "buses",
          paint: {
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
            "circle-color": [
              "case",
              ["!=", ["feature-state", "color"], null],
              ["feature-state", "color"],
              "#1a4731",
            ],
            "circle-opacity": 0.85,
            "circle-stroke-width": [
              "case",
              ["boolean", ["feature-state", "selected"], false],
              3,
              ["boolean", ["feature-state", "hovered"], false],
              2,
              0,
            ],
            "circle-stroke-color": [
              "case",
              ["boolean", ["feature-state", "selected"], false],
              "#38bdf8",
              "#ffffff",
            ],
          },
        });
      }

      // Hover interactions
      map.on("mousemove", "buses", (e) => {
        if (!e.features?.length) return;
        map.getCanvas().style.cursor = "crosshair";
        const feat = e.features[0];
        const props = feat.properties as Record<string, unknown>;
        callbacksRef.current.onBusHover(props.bus_id as string, props);

        tooltipRef.current
          ?.setLngLat(e.lngLat)
          .setHTML(
            `<div class="tip-id">${props.bus_id}</div>
             <div class="tip-zone">${props.load_zone ?? "—"}</div>`
          )
          .addTo(map);
      });

      map.on("mouseleave", "buses", () => {
        map.getCanvas().style.cursor = "";
        callbacksRef.current.onBusHover(null, null);
        tooltipRef.current?.remove();
      });
    };

    // Line hover
    map.on("mousemove", "lines-hit", (e) => {
      if (!e.features?.length) return;

      // If a bus is currently hovered, let bus tooltip win
      const busesAtPoint = map.queryRenderedFeatures(e.point, {
        layers: ["buses"],
      });
      if (busesAtPoint.length > 0) return;

      map.getCanvas().style.cursor = "crosshair";
      const feat = e.features[0];
      const props = feat.properties as Record<string, unknown>;
      const lineId = props.line_id as string;

      // Status precedence: contingency > binding > normal
      const conts = metaRef.current?.top_contingencies ?? [];
      const contIdx = conts.findIndex((c) => c.line === lineId);
      // Look up binding status from meta
      const binding = metaRef.current?.binding_lines?.find(
        (bl) => bl.line === lineId
      );

      let statusHtml: string;
      if (contIdx >= 0 && contIdx < 5) {
        const c = conts[contIdx];
        statusHtml = `<div class="tip-contingency">⚠ N-1 #${
          contIdx + 1
        } · stress ${c.stress.toFixed(2)}</div>`;
      } else if (binding) {
        statusHtml = `<div class="tip-binding">⚡ BINDING · $${binding.shadow_price.toFixed(
          1
        )}/MWh</div>`;
      } else {
        statusHtml = `<div class="tip-zone">normal</div>`;
      }

      callbacksRef.current.onLineHover(lineId, props);

      // PTDF halo: when the hovered line changes, debounce-fetch its column
      // and apply opacity to the responding buses. Cached client-side, so
      // re-hovering a line is instant.
      if (haloLineRef.current !== lineId) {
        if (haloDebounceRef.current !== null) {
          window.clearTimeout(haloDebounceRef.current);
        }
        // Clear previous halos immediately so we don't show stale ones while
        // the new fetch is in flight.
        clearHalos(map);
        haloLineRef.current = lineId;
        haloDebounceRef.current = window.setTimeout(() => {
          // Race guard — user may have moved off this line by now.
          if (haloLineRef.current !== lineId) return;
          fetchPtdf(lineId)
            .then((resp) => {
              if (haloLineRef.current !== lineId) return; // moved off
              applyHalos(map, resp.buses);
            })
            .catch(() => {
              // swallow — halos are non-critical, no UI for the error
            });
        }, 150);
      }

      tooltipRef.current
        ?.setLngLat(e.lngLat)
        .setHTML(
          `<div class="tip-id">${lineId}</div>
       ${statusHtml}`
        )
        .addTo(map);
    });

    map.on("mouseleave", "lines-hit", () => {
      map.getCanvas().style.cursor = "";
      callbacksRef.current.onLineHover(null, null);
      tooltipRef.current?.remove();
      // Clear halo state when leaving any line
      if (haloDebounceRef.current !== null) {
        window.clearTimeout(haloDebounceRef.current);
        haloDebounceRef.current = null;
      }
      haloLineRef.current = null;
      clearHalos(map);
    });

    // Click on a bus
    map.on("click", "buses", (e) => {
      if (!e.features?.length) return;
      e.preventDefault?.();
      const props = e.features[0].properties as Record<string, unknown>;
      callbacksRef.current.onBusClick(props.bus_id as string, props);
    });

    // Click on a line (use the invisible hit layer for fat clicks)
    map.on("click", "lines-hit", (e) => {
      if (!e.features?.length) return;
      // If a bus is here too, let it win
      const busesAtPoint = map.queryRenderedFeatures(e.point, {
        layers: ["buses"],
      });
      if (busesAtPoint.length > 0) return;
      e.preventDefault?.();
      const props = e.features[0].properties as Record<string, unknown>;
      callbacksRef.current.onLineClick(props.line_id as string, props);
    });

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
    // The map setup runs once on mount. Callbacks are accessed via
    // callbacksRef so they don't need to be in the deps; topology is the
    // only meaningful trigger for re-running this effect.
  }, [topology]);

  // Update binding-line highlights when meta changes
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource("lines")) return;

    const nextBinding = new Set(
      meta?.binding_lines?.map((bl) => bl.line) ?? []
    );

    // Clear previously-binding lines that aren't in the new set
    for (const lineId of prevBindingRef.current) {
      if (!nextBinding.has(lineId)) {
        map.setFeatureState(
          { source: "lines", id: lineId },
          { binding: false }
        );
      }
    }
    // Mark current binding lines
    for (const lineId of nextBinding) {
      map.setFeatureState({ source: "lines", id: lineId }, { binding: true });
    }
    prevBindingRef.current = nextBinding;
  }, [meta]);

  // Outage
  // Update contingency-line highlights (top 5) when meta changes
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource("lines")) return;

    const nextCont = new Set(
      (meta?.top_contingencies ?? []).slice(0, 5).map((c) => c.line)
    );

    for (const lineId of prevContingencyRef.current) {
      if (!nextCont.has(lineId)) {
        map.setFeatureState(
          { source: "lines", id: lineId },
          { contingency: false }
        );
      }
    }
    for (const lineId of nextCont) {
      map.setFeatureState(
        { source: "lines", id: lineId },
        { contingency: true }
      );
    }
    prevContingencyRef.current = nextCont;
  }, [meta]);

  // Update bus colors when buses/viewMode changes
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !buses.length || !map.getSource("buses")) return;

    const deltaMap =
      viewMode === "congestion_vs_basis"
        ? computeCongestionVsBasisRank(buses)
        : null;

    for (const bus of buses) {
      let color: string;
      if (viewMode === "modeled_congestion") {
        if (mcStats) {
          color = modeledCongestionColor(
            normalizeModeledCongestion(bus.modeled_congestion, mcStats)
          );
        } else {
          color = modeledCongestionColor(0);
        }
      } else if (viewMode === "lmp") {
        if (lmpStats) {
          color = lmpColor(normalizeLmpFromStats(bus.lmp, lmpStats));
        } else {
          color = lmpColor(0.5);
        }
      } else if (viewMode === "congestion_vs_basis") {
        color = rankDeltaColor(deltaMap!.get(bus.bus_id) ?? null);
      } else {
        // binding_proximity
        color = bindingProximityColor(normalizeProximity(bus.binding_proximity));
      }
      map.setFeatureState({ source: "buses", id: bus.bus_id }, { color });
    }
  }, [buses, viewMode, lmpStats, mcStats]);

  // Selected bus
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource("buses")) return;
    if (
      prevSelectedBusRef.current &&
      prevSelectedBusRef.current !== selectedBusId
    ) {
      map.setFeatureState(
        { source: "buses", id: prevSelectedBusRef.current },
        { selected: false }
      );
    }
    if (selectedBusId) {
      map.setFeatureState(
        { source: "buses", id: selectedBusId },
        { selected: true }
      );
    }
    prevSelectedBusRef.current = selectedBusId;
  }, [selectedBusId]);

  // Selected line
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource("lines")) return;
    if (
      prevSelectedLineRef.current &&
      prevSelectedLineRef.current !== selectedLineId
    ) {
      map.setFeatureState(
        { source: "lines", id: prevSelectedLineRef.current },
        { selected: false }
      );
    }
    if (selectedLineId) {
      map.setFeatureState(
        { source: "lines", id: selectedLineId },
        { selected: true }
      );
    }
    prevSelectedLineRef.current = selectedLineId;
  }, [selectedLineId]);

  return (
    <>
      <div ref={containerRef} style={{ width: "100%", height: "100%" }} />
      <canvas ref={canvasRef} style={{ display: "none" }} />
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
        .tip-binding { color: #ec4899; font-size: 10px; margin-top: 2px; font-weight: 600; }
        .tip-contingency { color: #cbd5e1; font-size: 10px; margin-top: 2px; }
      `}</style>
    </>
  );
}
