import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type {
  SpRow,
  MapDataMode,
  ConstraintReach,
  MapOverview,
} from "../../api/types";
import OverviewPopover from "./OverviewPopover";
import {
  buildOverviewSources,
  buildSpMembers,
  type OvMember,
} from "./overviewSources";
import {
  lmpColor,
  isLocalExtreme,
  localExtremeThreshold,
  normalizeLmpFromStats,
  congestionColor as congestionRampColor,
  congestionAlarmColor,
  normalizeCongestion,
  shiftFactorColor,
  type LmpStats,
  type CongestionStats,
} from "../../lib/colors";
import { cssVar, onThemeChange, useTheme, type Theme } from "../../lib/theme";

// Animate node color changes between playback hours.
const TWEEN_MS = 300;
const prefersReducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;

// MapLibre needs resolved theme colors rather than CSS variables.
function chromeColors() {
  return {
    label: cssVar("--map-label"),
    halo: cssVar("--map-halo"),
    outline: cssVar("--map-outline"),
    outlineFill: cssVar("--map-outline-fill"),
    nodeNull: cssVar("--map-node-null"),
    nodeHover: cssVar("--map-node-hover"),
    aggregateLabel: cssVar("--map-aggregate-label"),
    accent: cssVar("--accent"),
  };
}

function spRadius(): maplibregl.ExpressionSpecification {
  return [
    "interpolate", ["linear"], ["zoom"],
    4, ["match", ["get", "sp_type"], "hub", 6.5, "load_zone", 0, 3],
    8, ["match", ["get", "sp_type"], "hub", 10.5, "load_zone", 0, 5.5],
    12, ["match", ["get", "sp_type"], "hub", 15, "load_zone", 0, 9],
  ] as maplibregl.ExpressionSpecification;
}

function spStrokeWidth(): maplibregl.ExpressionSpecification {
  return [
    "case",
    ["boolean", ["feature-state", "selected"], false], 5,
    ["boolean", ["feature-state", "ringed"], false], 4,
    ["boolean", ["feature-state", "hovered"], false], 4,
    ["match", ["get", "sp_type"], "hub", 1.75, 0],
  ] as maplibregl.ExpressionSpecification;
}

function fanOutAggregateMarkers(points: GeoJSON.FeatureCollection): GeoJSON.FeatureCollection {
  const features = points.features.map((feature) => ({
    ...feature,
    properties: { ...(feature.properties ?? {}) },
  }));
  const groups = new Map<string, typeof features>();
  for (const feature of features) {
    const props = feature.properties as Record<string, unknown>;
    const coords = feature.geometry?.type === "Point" ? feature.geometry.coordinates : null;
    if (!coords || (props.sp_type !== "hub" && props.sp_type !== "load_zone")) continue;
    props.aggregate_marker_offset = [0, 0];
    const key = `${coords[0]},${coords[1]}`;
    groups.set(key, [...(groups.get(key) ?? []), feature]);
  }
  for (const group of groups.values()) {
    if (group.length < 2) continue;
    group.sort((a, b) => {
      const aProps = a.properties as Record<string, unknown>;
      const bProps = b.properties as Record<string, unknown>;
      const aType = aProps.sp_type === "hub" ? 0 : 1;
      const bType = bProps.sp_type === "hub" ? 0 : 1;
      return aType - bType || String(aProps.sp_id).localeCompare(String(bProps.sp_id));
    });
    const offsets = group.length === 2
      ? [[-0.55, 0], [0.55, 0]]
      : [[-0.7, 0.5], [0.7, -0.5], [-0.7, -0.5], [0.7, 0.5]];
    group.forEach((feature, index) => {
      (feature.properties as Record<string, unknown>).aggregate_marker_offset =
        offsets[index % offsets.length];
    });
  }
  return { ...points, features };
}

function spStrokeColor(chrome: ReturnType<typeof chromeColors>): maplibregl.ExpressionSpecification {
  return [
    "case",
    ["boolean", ["feature-state", "selected"], false], chrome.nodeHover,
    ["boolean", ["feature-state", "ringed"], false], chrome.nodeHover,
    ["boolean", ["feature-state", "hovered"], false], chrome.accent,
    ["match", ["get", "sp_type"], "hub", chrome.nodeHover, chrome.accent],
  ] as maplibregl.ExpressionSpecification;
}

// City labels provide map orientation without a basemap.
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
  points: unknown | null;
  rows: SpRow[];
  dataMode: MapDataMode;
  lmpStats: LmpStats | null;
  mcStats: CongestionStats | null;
  onSpHover: (
    spId: string | null,
    props: Record<string, unknown> | null
  ) => void;
  onSpClick: (spId: string, props: Record<string, unknown>) => void;
  onMapClick: () => void;
  selectedSpId: string | null;
  // Show or hide constraint marks.
  showConstraints?: boolean;
  // Constraint marks drawn beneath settlement points.
  overview?: MapOverview | null;
  // Highlight one constraint mark and report mark hover.
  isolatedConstraint?: string | null;
  onIsolateConstraint?: (id: string | null) => void;
  // Recolor nodes for the highlighted constraint without opening a card.
  focusReach?: ConstraintReach | null;
  ringedSpId?: string | null;
  onConstraintPreview?: (key: string | null) => void;
  onConstraintSelect?: (key: string) => void;
  // Selected constraint footprint; overrides normal node colors.
  reach?: ConstraintReach | null;
  side?: "prediction" | "actual";
  onMapReady?: (map: maplibregl.Map) => void;
  // Optional congestion palette for forecast error.
  congestionColor?: (norm: number, theme: Theme) => string;
  // Disable hover-only interactions on touch screens.
  tapOnly?: boolean;
}

export default function GridMap({
  points,
  rows,
  dataMode,
  lmpStats,
  mcStats,
  onSpHover,
  onSpClick,
  onMapClick,
  selectedSpId,
  showConstraints = true,
  reach,
  overview,
  isolatedConstraint = null,
  onIsolateConstraint,
  focusReach = null,
  ringedSpId = null,
  onConstraintPreview,
  onConstraintSelect,
  onMapReady,
  congestionColor = congestionRampColor,
  tapOnly = false,
}: Props) {
  const theme = useTheme();
  const prevSelectedRef = useRef<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  // Wait for the settlement-point source before updating feature state.
  const [sourcesReady, setSourcesReady] = useState(false);
  const [containerWidth, setContainerWidth] = useState(0);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const alarmMarkersRef = useRef<
    Map<string, { marker: maplibregl.Marker; element: HTMLDivElement }>
  >(new Map());
  const tapOnlyRef = useRef(tapOnly);
  const onMapReadyRef = useRef(onMapReady);
  useEffect(() => {
    onMapReadyRef.current = onMapReady;
  }, [onMapReady]);

  // Map event handlers read current callbacks without rebinding.
  const callbacksRef = useRef({
    onSpHover,
    onSpClick,
    onMapClick,
    onIsolateConstraint,
    onConstraintPreview,
    onConstraintSelect,
  });
  useEffect(() => {
    callbacksRef.current = {
      onSpHover,
      onSpClick,
      onMapClick,
      onIsolateConstraint,
      onConstraintPreview,
      onConstraintSelect,
    };
  }, [
    onSpHover,
    onSpClick,
    onMapClick,
    onIsolateConstraint,
    onConstraintPreview,
    onConstraintSelect,
  ]);

  const [popover, setPopover] = useState<{
    name: string;
    kind: "node" | "gtc" | "transmission";
    members?: OvMember[];
    meta?: string | null;
    x: number;
    y: number;
  } | null>(null);
  // Keep member popovers open while moving the pointer into them.
  const popoverRef = useRef(popover);
  useEffect(() => {
    popoverRef.current = popover;
  }, [popover]);
  const overStickyNodeCard = () => {
    const p = popoverRef.current;
    return p?.kind === "node" && !!p.members?.length;
  };
  useEffect(() => {
    tapOnlyRef.current = tapOnly;
    if (tapOnly) mapRef.current?.getCanvas().style.setProperty("cursor", "");
  }, [tapOnly]);
  const hoveredNodeHasMembersRef = useRef(false);
  const spMembers = useMemo(() => buildSpMembers(overview ?? null), [overview]);
  const spMembersRef = useRef(spMembers);
  useEffect(() => {
    spMembersRef.current = spMembers;
  }, [spMembers]);
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
    onMapReadyRef.current?.(map);
    // Resize when a single map becomes a split pane.
    const resizeObserver = new ResizeObserver((entries) => {
      map.resize();
      setContainerWidth(entries[0]?.contentRect.width ?? 0);
    });
    resizeObserver.observe(containerRef.current);
    const alarmMarkers = alarmMarkersRef.current;
    return () => {
      resizeObserver.disconnect();
      for (const { marker } of alarmMarkers.values()) marker.remove();
      alarmMarkers.clear();
      map.remove();
      mapRef.current = null;
      setSourcesReady(false);
    };
  }, []);

  // Refresh MapLibre paint values after a theme change.
  useEffect(() => {
    return onThemeChange(() => {
      const map = mapRef.current;
      if (!map || !map.isStyleLoaded()) return;
      const c = chromeColors();

      const set = (layer: string, prop: string, value: unknown) => {
        if (map.getLayer(layer)) map.setPaintProperty(layer, prop, value);
      };

      set("texas-fill", "fill-color", c.outlineFill);
      set("texas-line", "line-color", c.outline);
      set("city-labels", "text-color", c.label);
      set("city-labels", "text-halo-color", c.halo);
      set("sps", "circle-stroke-color", spStrokeColor(c));
      set("sps", "circle-color", [
        "case",
        ["!=", ["feature-state", "color"], null],
        ["feature-state", "color"],
        c.nodeNull,
      ]);
      set("load-zone-diamonds", "text-color", [
        "case",
        ["!=", ["feature-state", "color"], null],
        ["feature-state", "color"],
        c.nodeNull,
      ]);
      set("load-zone-diamonds", "text-halo-color", [
        "case",
        ["boolean", ["feature-state", "hovered"], false], c.accent,
        c.nodeHover,
      ]);
      set("aggregate-labels", "text-color", c.aggregateLabel);
    });
  }, []);

  // Load settlement points and base layers.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !points) return;

    const fc = fanOutAggregateMarkers(points as GeoJSON.FeatureCollection);

    const onLoad = () => {
      if (!map.getSource("sps")) {
        map.addSource("sps", {
          type: "geojson",
          data: fc,
          promoteId: "sp_id",
        });
      }

      const chrome = chromeColors();

      if (!map.getSource("texas")) {
        map.addSource("texas", { type: "geojson", data: "/texas.geojson" });
      }
      if (!map.getLayer("texas-fill")) {
        map.addLayer({
          id: "texas-fill",
          type: "fill",
          source: "texas",
          paint: { "fill-color": chrome.outlineFill },
        });
      }
      if (!map.getLayer("texas-line")) {
        map.addLayer({
          id: "texas-line",
          type: "line",
          source: "texas",
          layout: { "line-join": "round" },
          paint: {
            "line-color": chrome.outline,
            "line-width": [
              "interpolate",
              ["linear"],
              ["zoom"],
              4,
              0.8,
              8,
              1.4,
              12,
              2,
            ],
          },
        });
      }

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
            "text-color": chrome.label,
            "text-halo-color": chrome.halo,
            "text-halo-width": 1.2,
            "text-opacity": 0.75,
          },
        });
      }

      if (!map.getLayer("sps")) {
        map.addLayer({
          id: "sps",
          type: "circle",
          source: "sps",
          filter: ["all",
            ["!=", ["get", "sp_type"], "load_zone"],
          ],
          paint: {
            "circle-color": [
              "case",
              ["!=", ["feature-state", "color"], null],
              ["feature-state", "color"],
              chrome.nodeNull,
            ],
            "circle-opacity": [
              "case",
              ["boolean", ["feature-state", "faded"], false],
              0.08,
              0.9,
            ],
            "circle-radius": spRadius(),
            "circle-stroke-width": spStrokeWidth(),
            "circle-stroke-color": spStrokeColor(chrome),
            "circle-stroke-opacity": [
              "case",
              ["boolean", ["feature-state", "faded"], false],
              0,
              1,
            ],
          },
        });
      }

      if (!map.getLayer("load-zone-diamonds")) {
        map.addLayer({
          id: "load-zone-diamonds",
          type: "symbol",
          source: "sps",
          filter: ["==", ["get", "sp_type"], "load_zone"],
          layout: {
            "text-field": "◆",
            "text-font": ["Noto Sans Regular"],
            "text-size": ["interpolate", ["linear"], ["zoom"], 4, 18, 8, 28, 12, 38],
            "text-offset": ["get", "aggregate_marker_offset"],
            "text-allow-overlap": true,
            "text-ignore-placement": true,
          },
          paint: {
            "text-color": [
              "case",
              ["!=", ["feature-state", "color"], null],
              ["feature-state", "color"],
              chrome.nodeNull,
            ],
            "text-opacity": [
              "case",
              ["boolean", ["feature-state", "faded"], false],
              0,
              0.9,
            ],
            "text-halo-width": [
              "case",
              ["boolean", ["feature-state", "selected"], false], 3,
              ["boolean", ["feature-state", "ringed"], false], 2.5,
              ["boolean", ["feature-state", "hovered"], false], 2.5,
              1.5,
            ],
            "text-halo-color": [
              "case",
              ["boolean", ["feature-state", "hovered"], false], chrome.accent,
              chrome.nodeHover,
            ],
          },
        });
      }

      if (!map.getLayer("aggregate-labels")) {
        map.addLayer({
          id: "aggregate-labels",
          type: "symbol",
          source: "sps",
          filter: ["in", ["get", "sp_type"], ["literal", ["hub", "load_zone"]]],
          layout: {
            "text-field": ["match", ["get", "sp_type"], "hub", "H", "Z"],
            "text-font": ["Noto Sans Regular"],
            "text-size": ["interpolate", ["linear"], ["zoom"], 4, 10, 8, 14, 12, 17],
            "text-offset": [
              "case",
              ["==", ["get", "sp_type"], "load_zone"],
              ["get", "aggregate_marker_offset"],
              ["literal", [0, 0]],
            ],
            "text-allow-overlap": true,
            "text-ignore-placement": true,
          },
          paint: {
            "text-color": chrome.aggregateLabel,
            "text-halo-width": 0,
            "text-opacity": [
              "case",
              ["boolean", ["feature-state", "faded"], false],
              0,
              1,
            ],
          },
        });
      }

      const handleSpMove = (e: maplibregl.MapLayerMouseEvent) => {
        if (tapOnlyRef.current) return;
        if (!e.features?.length) return;
        map.getCanvas().style.cursor = "crosshair";
        const props = e.features[0].properties as Record<string, unknown>;
        const sp = props.sp_id as string;
        callbacksRef.current.onSpHover(sp, props);
        const mem = spMembersRef.current.get(sp);
        const hasMembers = !!mem && mem.length >= 2;
        hoveredNodeHasMembersRef.current = hasMembers;
        setPopover({
          name: sp,
          kind: "node",
          members: hasMembers ? mem : undefined,
          meta: typeof props.load_zone === "string" ? props.load_zone : null,
          x: e.point.x,
          y: e.point.y,
        });
      };
      for (const layer of ["sps", "load-zone-diamonds"]) {
        map.on("mousemove", layer, handleSpMove);
      }

      const handleSpLeave = () => {
        if (tapOnlyRef.current) return;
        map.getCanvas().style.cursor = "";
        callbacksRef.current.onSpHover(null, null);
        if (!hoveredNodeHasMembersRef.current) setPopover(null);
      };
      for (const layer of ["sps", "load-zone-diamonds"]) {
        map.on("mouseleave", layer, handleSpLeave);
      }

      const handleSpClick = (e: maplibregl.MapLayerMouseEvent, layer: string) => {
        if (!e.features?.length) return;
        // Prefer an overlapping load-zone marker.
        if (layer === "sps" && map.queryRenderedFeatures(e.point, {
          layers: ["load-zone-diamonds"],
        }).length) return;
        e.preventDefault?.();
        const props = e.features[0].properties as Record<string, unknown>;
        callbacksRef.current.onSpClick(props.sp_id as string, props);
      };
      for (const layer of ["sps", "load-zone-diamonds"]) {
        map.on("click", layer, (e) => handleSpClick(e, layer));
      }

      setSourcesReady(true);
    };

    // Clear selection when the map background is clicked.
    map.on("click", (e) => {
      if (e.defaultPrevented) return;
      setPopover(null);
      callbacksRef.current.onMapClick();
    });

    if (map.isStyleLoaded()) {
      onLoad();
    } else {
      map.once("load", onLoad);
    }
  }, [points]);

  // Update node colors when data or the active palette changes.
  const reachIdsRef = useRef<Set<string>>(new Set());
  const normValsRef = useRef<Map<string, number>>(new Map());
  const lastColorRef = useRef<Map<string, string>>(new Map());
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource("sps") || !points) return;
    const fc = points as GeoJSON.FeatureCollection<
      GeoJSON.Point,
      { sp_id: string }
    >;

    // Highlight the full reach; use overview nodes only while it loads.
    const rch = focusReach ?? reach;
    const members =
      rch && rch.sps.length > 0
        ? rch.sps
        : isolatedConstraint
        ? overview?.constraints.find(
            (c) => c.constraint_key === isolatedConstraint
          )?.nodes ?? null
        : null;
    if (members && members.length > 0) {
      const bySp = new Map<string, number>();
      for (const s of members) {
        bySp.set(s.settlement_point, s.sf);
      }
      const touched = new Set<string>();
      for (const feat of fc.features) {
        const id = feat.properties.sp_id;
        const sf = bySp.get(id);
        if (sf === undefined) {
          map.setFeatureState(
            { source: "sps", id },
            { color: null, faded: true }
          );
        } else {
          map.setFeatureState(
            { source: "sps", id },
            { color: shiftFactorColor(sf), faded: false }
          );
        }
        touched.add(id);
      }
      reachIdsRef.current = touched;
      lastColorRef.current.clear(); // reach overwrote fills; force a full repaint next
      return;
    }

    if (reachIdsRef.current.size) {
      for (const id of reachIdsRef.current) {
        map.setFeatureState({ source: "sps", id }, { faded: false });
      }
      reachIdsRef.current = new Set();
    }

    if (!rows.length) {
      for (const feat of fc.features) {
        map.setFeatureState(
          { source: "sps", id: feat.properties.sp_id },
          { color: null }
        );
      }
      normValsRef.current.clear();
      lastColorRef.current.clear();
      return;
    }

    const base =
      dataMode === "congestion"
        ? (nv: number) => congestionColor(nv, theme)
        : (nv: number) => lmpColor(nv, theme);
    const rampCache = new Map<number, string>();
    const ramp = (nv: number) => {
      const key = Math.round(nv * 512);
      let c = rampCache.get(key);
      if (c === undefined) { c = base(nv); rampCache.set(key, c); }
      return c;
    };
    const targets = new Map<string, number>();
    for (const row of rows) {
      const nv =
        dataMode === "congestion"
          ? mcStats
            ? normalizeCongestion(row.congestion)
            : 0
          : lmpStats
          ? normalizeLmpFromStats(row.spp)
          : 0.5;
      targets.set(row.sp_id, nv);
    }

    // Continue transitions from the current on-screen color.
    const norms = normValsRef.current;
    const start = new Map(norms);
    const paint = (frac: number) => {
      for (const [id, target] of targets) {
        const from = start.get(id) ?? target;
        const nv = from + (target - from) * frac;
        norms.set(id, nv);
        const color = ramp(nv);
        if (lastColorRef.current.get(id) === color) continue; // unchanged → skip
        lastColorRef.current.set(id, color);
        map.setFeatureState({ source: "sps", id }, { color });
      }
    };

    if (start.size === 0 || prefersReducedMotion()) {
      paint(1);
      return;
    }

    // Limit color transitions to 30 fps.
    let rafId = 0;
    let lastPaint = 0;
    const t0 = performance.now();
    const tick = (now: number) => {
      const frac = Math.min(1, (now - t0) / TWEEN_MS);
      if (frac >= 1 || now - lastPaint >= 1000 / 30) {
        paint(1 - (1 - frac) ** 3); // ease-out cubic
        lastPaint = now;
      }
      rafId = frac < 1 ? requestAnimationFrame(tick) : 0;
    };
    rafId = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(rafId);
  }, [
    rows,
    dataMode,
    lmpStats,
    mcStats,
    points,
    sourcesReady,
    reach,
    focusReach,
    isolatedConstraint,
    overview,
    congestionColor,
    theme,
  ]);

  // DOM markers provide animated halos over MapLibre data layers.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !points || !sourcesReady) return;

    const rch = focusReach ?? reach;
    const focusMembers =
      rch?.sps.length ||
      (isolatedConstraint
        ? overview?.constraints.find((c) => c.constraint_key === isolatedConstraint)
            ?.nodes.length
        : 0);
    const desired = new Map<string, [number, number]>();
    const alarmThreshold = localExtremeThreshold(
      rows.map((row) => dataMode === "congestion" ? row.congestion : row.spp),
      dataMode === "congestion"
    );
    const alarmColor =
      dataMode === "congestion"
        ? congestionAlarmColor(theme)
        : lmpColor(1, theme);
    if (
      !focusMembers &&
      ((dataMode === "congestion" && mcStats) || (dataMode === "lmp" && lmpStats))
    ) {
      const coordinates = new Map<string, [number, number]>();
      for (const feature of (points as GeoJSON.FeatureCollection).features) {
        if (feature.geometry?.type !== "Point") continue;
        const props = feature.properties as { sp_id?: string } | null;
        const [lng, lat] = feature.geometry.coordinates;
        if (props?.sp_id && Number.isFinite(lng) && Number.isFinite(lat)) {
          coordinates.set(props.sp_id, [lng, lat]);
        }
      }
      for (const row of rows) {
        const coordinate = coordinates.get(row.sp_id);
        const alarm =
          dataMode === "congestion"
            ? !!mcStats && isLocalExtreme(row.congestion, alarmThreshold)
            : !!lmpStats && isLocalExtreme(row.spp, alarmThreshold);
        if (coordinate && alarm) {
          desired.set(row.sp_id, coordinate);
        }
      }
    }

    for (const [spId, current] of alarmMarkersRef.current) {
      if (desired.has(spId)) continue;
      current.marker.remove();
      alarmMarkersRef.current.delete(spId);
    }
    for (const [spId, coordinate] of desired) {
      const current = alarmMarkersRef.current.get(spId);
      if (current) {
        current.element.style.setProperty("--alarm-halo", alarmColor);
        continue;
      }
      const element = document.createElement("div");
      element.className = "map-alarm-halo";
      element.setAttribute("aria-hidden", "true");
      element.style.setProperty("--alarm-halo", alarmColor);
      element.style.pointerEvents = "none";
      const marker = new maplibregl.Marker({ element, anchor: "center" })
        .setLngLat(coordinate)
        .addTo(map);
      alarmMarkersRef.current.set(spId, { marker, element });
    }
  }, [
    rows,
    dataMode,
    mcStats,
    lmpStats,
    points,
    sourcesReady,
    reach,
    focusReach,
    isolatedConstraint,
    overview,
    theme,
  ]);

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

  const prevRingedRef = useRef<string | null>(null);
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource("sps")) return;
    if (prevRingedRef.current && prevRingedRef.current !== ringedSpId) {
      map.setFeatureState(
        { source: "sps", id: prevRingedRef.current },
        { ringed: false }
      );
    }
    if (ringedSpId) {
      map.setFeatureState({ source: "sps", id: ringedSpId }, { ringed: true });
    }
    prevRingedRef.current = ringedSpId ?? null;
  }, [ringedSpId, sourcesReady]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !sourcesReady) return;
    if (map.getLayer("reach-corridor")) map.removeLayer("reach-corridor");
    if (map.getSource("reach-corridor")) map.removeSource("reach-corridor");
  }, [sourcesReady]);

  // Draw constraint marks below settlement points.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !sourcesReady) return;

    const apply = () => {
      const src = buildOverviewSources(
        showConstraints ? overview ?? null : null
      );
      const sf = {
        gtc: cssVar("--sf-gtc"),
        transmission: cssVar("--sf-transmission"),
        radial: cssVar("--sf-radial"),
        lineOpacity: Number(cssVar("--sf-line-opacity")),
      };
      const setData = (id: string, data: GeoJSON.FeatureCollection) => {
        const s = map.getSource(id) as maplibregl.GeoJSONSource | undefined;
        if (s) s.setData(data);
        else map.addSource(id, { type: "geojson", data });
      };
      setData("ov-gtc-axis", src.gtcAxis);
      setData("ov-gtc-gate", src.gtcGate);
      setData("ov-gtc-hit", src.gtcHit);
      setData("ov-corridor", src.corridor);
      setData("ov-radial", src.radial);

      const before = map.getLayer("sps") ? "sps" : undefined;
      if (!map.getLayer("ov-gtc-axis")) {
        map.addLayer(
          {
            id: "ov-gtc-axis",
            type: "line",
            source: "ov-gtc-axis",
            layout: { "line-cap": "round" },
            paint: {
              "line-color": sf.gtc,
              "line-width": 1.2,
              "line-opacity": 0.7,
              "line-dasharray": [2, 2],
            },
          },
          before
        );
      }
      if (!map.getLayer("ov-gtc-gate")) {
        map.addLayer(
          {
            id: "ov-gtc-gate",
            type: "line",
            source: "ov-gtc-gate",
            layout: { "line-cap": "round" },
            paint: {
              "line-color": sf.gtc,
              "line-width": 2.2,
              "line-opacity": 0.9,
            },
          },
          before
        );
      }
      // Larger hit area for thin GTC gates.
      if (!map.getLayer("ov-gtc-hit")) {
        map.addLayer(
          {
            id: "ov-gtc-hit",
            type: "circle",
            source: "ov-gtc-hit",
            paint: {
              "circle-color": sf.gtc,
              "circle-radius": 8,
              "circle-opacity": 0.01,
            },
          },
          before
        );
      }
      if (!map.getLayer("ov-corridor")) {
        map.addLayer(
          {
            id: "ov-corridor",
            type: "line",
            source: "ov-corridor",
            layout: { "line-cap": "round", "line-join": "round" },
            paint: {
              "line-color": sf.transmission,
              "line-width": 1.35,
              "line-opacity": sf.lineOpacity,
            },
          },
          before
        );
      }
      // Larger hit area for transmission corridors.
      if (!map.getLayer("ov-corridor-hit")) {
        map.addLayer(
          {
            id: "ov-corridor-hit",
            type: "line",
            source: "ov-corridor",
            layout: { "line-cap": "round", "line-join": "round" },
            paint: {
              "line-color": sf.transmission,
              "line-width": 12,
              "line-opacity": 0.01,
            },
          },
          before
        );
      }
      if (!map.getLayer("ov-radial")) {
        map.addLayer(
          {
            id: "ov-radial",
            type: "circle",
            source: "ov-radial",
            paint: {
              "circle-color": "rgba(0,0,0,0)",
              "circle-radius": [
                "interpolate",
                ["linear"],
                ["zoom"],
                4,
                4,
                8,
                6,
                12,
                9,
              ],
              "circle-stroke-color": sf.radial,
              "circle-stroke-width": 2,
            },
          },
          before
        );
      }

      map.setPaintProperty("ov-gtc-axis", "line-color", sf.gtc);
      map.setPaintProperty("ov-gtc-gate", "line-color", sf.gtc);
      map.setPaintProperty("ov-gtc-hit", "circle-color", sf.gtc);
      map.setPaintProperty("ov-corridor", "line-color", sf.transmission);
      map.setPaintProperty("ov-corridor", "line-opacity", sf.lineOpacity);
      map.setPaintProperty("ov-radial", "circle-stroke-color", sf.radial);
      const filt = (
        isolatedConstraint
          ? ["==", ["get", "constraint_key"], isolatedConstraint]
          : ["all"]
      ) as maplibregl.FilterSpecification;
      for (const id of ["ov-gtc-axis", "ov-gtc-gate", "ov-gtc-hit", "ov-radial"])
        map.setFilter(id, filt);
      map.setFilter("ov-corridor", filt);
      map.setFilter("ov-corridor-hit", filt);
    };

    apply();
  }, [
    overview,
    showConstraints,
    isolatedConstraint,
    sourcesReady,
    theme,
    selectedSpId,
    reach,
    focusReach,
  ]);

  // Preview constraints on hover; touch screens select on tap.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !sourcesReady || !map.getLayer("ov-gtc-hit")) return;

    const hitLayers = ["ov-gtc-hit", "ov-corridor-hit"];
    const overSettlementPoint = (e: maplibregl.MapLayerMouseEvent) =>
      map.queryRenderedFeatures(e.point, { layers: ["sps", "load-zone-diamonds"] }).length > 0;
    const keyAt = (e: maplibregl.MapLayerMouseEvent) =>
      e.features?.[0]?.properties?.constraint_key as string | undefined;
    const kindAt = (e: maplibregl.MapLayerMouseEvent) =>
      e.features?.[0]?.properties?.ctype === "transmission" ? "transmission" : "gtc";
    const onEnter = (e: maplibregl.MapLayerMouseEvent) => {
      if (overStickyNodeCard() || overSettlementPoint(e)) return;
      const key = keyAt(e);
      if (!key) return;
      map.getCanvas().style.cursor = "pointer";
      setPopover({ name: key, kind: kindAt(e), x: e.point.x, y: e.point.y });
      callbacksRef.current.onIsolateConstraint?.(key);
      callbacksRef.current.onConstraintPreview?.(key);
    };
    const onMove = (e: maplibregl.MapLayerMouseEvent) => {
      if (overStickyNodeCard() || overSettlementPoint(e)) return;
      const key = keyAt(e);
      if (key) setPopover({ name: key, kind: kindAt(e), x: e.point.x, y: e.point.y });
    };
    const onLeave = () => {
      if (overStickyNodeCard()) return;
      map.getCanvas().style.cursor = "";
      setPopover(null);
      callbacksRef.current.onIsolateConstraint?.(null);
      callbacksRef.current.onConstraintPreview?.(null);
    };
    const onClick = (e: maplibregl.MapLayerMouseEvent) => {
      if (overSettlementPoint(e)) return;
      const key = keyAt(e);
      if (!key) return;
      e.preventDefault();
      callbacksRef.current.onConstraintSelect?.(key);
      setPopover(null);
    };
    if (!tapOnly) {
      map.on("mouseenter", hitLayers, onEnter);
      map.on("mousemove", hitLayers, onMove);
      map.on("mouseleave", hitLayers, onLeave);
    }
    map.on("click", hitLayers, onClick);
    return () => {
      if (!tapOnly) {
        map.off("mouseenter", hitLayers, onEnter);
        map.off("mousemove", hitLayers, onMove);
        map.off("mouseleave", hitLayers, onLeave);
      }
      map.off("click", hitLayers, onClick);
    };
  }, [sourcesReady, tapOnly]);

  const visiblePopover = showConstraints && !tapOnly ? popover : null;

  return (
    <>
      <div
        ref={containerRef}
        style={{ width: "100%", height: "100%", position: "relative" }}
      >
        {visiblePopover && (
          <OverviewPopover
            name={visiblePopover.name}
            kind={visiblePopover.kind}
            members={visiblePopover.members}
            meta={visiblePopover.meta}
            x={visiblePopover.x}
            y={visiblePopover.y}
            containerWidth={containerWidth}
            onRowHover={(key) => {
              onIsolateConstraint?.(key);
              onConstraintPreview?.(key);
            }}
            onRowClick={(key) => {
              onConstraintSelect?.(key);
              setPopover(null);
            }}
            onLeave={() => {
              onIsolateConstraint?.(null);
              onConstraintPreview?.(null);
              setPopover(null);
            }}
          />
        )}
      </div>
      <style>{`
        .maplibregl-ctrl-group {
          background: var(--bg-panel) !important;
          border: 1px solid var(--border) !important;
        }
        .maplibregl-ctrl-group button {
          background: transparent !important;
          border: none !important;
          padding: 0 !important;
        }
        /* maplibre ships black control glyphs, so the dark theme inverts them.
           Light must NOT invert, or the icons go white-on-white. */
        .maplibregl-ctrl-zoom-in .maplibregl-ctrl-icon,
        .maplibregl-ctrl-zoom-out .maplibregl-ctrl-icon {
          filter: invert(1) opacity(0.6);
        }
        :root[data-theme='light'] .maplibregl-ctrl-zoom-in .maplibregl-ctrl-icon,
        :root[data-theme='light'] .maplibregl-ctrl-zoom-out .maplibregl-ctrl-icon {
          filter: opacity(0.65);
        }
        .map-alarm-halo {
          width: 32px;
          height: 32px;
          pointer-events: none;
        }
        .map-alarm-halo::after {
          content: "";
          position: absolute;
          inset: 0;
          box-sizing: border-box;
          border: 2px solid var(--alarm-halo);
          border-radius: 50%;
          box-shadow: 0 0 8px var(--alarm-halo);
          animation: map-alarm-halo-pulse 1.8s ease-out infinite;
        }
        @keyframes map-alarm-halo-pulse {
          0% { opacity: 0.95; transform: scale(0.45); }
          72% { opacity: 0; transform: scale(1.45); }
          100% { opacity: 0; transform: scale(1.45); }
        }
        @media (prefers-reduced-motion: reduce) {
          .map-alarm-halo::after {
            animation: none;
            opacity: 0.9;
            transform: scale(0.8);
          }
        }
      `}</style>
    </>
  );
}
