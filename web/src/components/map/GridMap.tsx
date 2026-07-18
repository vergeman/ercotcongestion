import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type {
  SpRow,
  Palette,
  ConstraintGeo,
  ConstraintReach,
  MapOverview,
} from "../../api/types";
import OverviewOverlay from "./OverviewOverlay";
import {
  lmpColor,
  normalizeLmpFromStats,
  modeledCongestionColor,
  normalizeModeledCongestion,
  type LmpStats,
  type ModeledCongestionStats,
} from "../../lib/colors";

// Constraint-overlay identity hue (violet). Distinct from the node palettes
// (diverging blue/cream/red congestion; blue/orange LMP) so the SF-structure
// layer never reads as a node value. Marker size — not color — encodes
// magnitude (max |SF|); a highlighted driver gets the bright ring + full fill.
const CONSTRAINT_FILL = "rgba(167, 139, 250, 0.55)"; // #a78bfa @ 0.55
const CONSTRAINT_FILL_HI = "rgba(167, 139, 250, 0.95)";
const CONSTRAINT_STROKE = "#c4b5fd";
const CONSTRAINT_R_MIN = 4;
const CONSTRAINT_R_MAX = 20;

// Low-confidence styling: a muted slate, distinct from the violet, so a
// weakly-fit constraint reads as "located but don't trust its geometry". Low
// confidence is a *shape* verdict, not an hour count (docs/ERCOT_constraints.md
// §4): the artifact is the ridge clamp — several nodes co-equal at the ±1 cap,
// or a lone rail with no graded body beneath it. A single rail atop a real body
// (a radial resource) or any unclipped graded SF is NOT low-confidence, even if
// it bound only briefly. binding_hours is a separate "thin support" annotation.
const CONSTRAINT_FILL_LOW = "rgba(148, 163, 184, 0.35)"; // slate-400 muted
const CONSTRAINT_STROKE_LOW = "#94a3b8";
const RAIL_MULTI = 2;      // >= this many nodes at the cap = clamp artifact
const BODY_FLOOR = 0.1;    // a rail with peak_offrail below this has no real body
const THIN_HOURS = 50;     // annotation threshold, not a verdict

function isLowConfidence(c: ConstraintGeo): boolean {
  const nRail = c.n_rail ?? 0;
  if (nRail >= RAIL_MULTI) return true;
  // A single rail is only suspect when nothing graded sits beneath it (an
  // isolated spike straight to the noise floor). A rail atop a real body is a
  // radial resource — trustworthy.
  return nRail >= 1 && (c.peak_offrail == null || c.peak_offrail < BODY_FLOOR);
}

// Thin support is a caveat, not a disqualifier — clean-but-brief constraints
// bind < THIN_HOURS yet have smooth, unclipped SF (docs §4).
function isThinSupport(c: ConstraintGeo): boolean {
  return c.binding_hours != null && c.binding_hours < THIN_HOURS;
}

// Build the overlay FeatureCollection, baking a per-feature radius from
// max_abs_sf. Radius ∝ √value so circle *area* is proportional to magnitude
// (Steven's-law-honest area encoding), normalized to the window's own max.
function buildConstraintFC(
  constraints: ConstraintGeo[]
): GeoJSON.FeatureCollection<GeoJSON.Point> {
  const withGeo = constraints.filter((c) => c.lat != null && c.lon != null);
  const maxVal = withGeo.reduce(
    (m, c) => Math.max(m, c.max_abs_sf ?? 0),
    1e-9
  );
  return {
    type: "FeatureCollection",
    features: withGeo.map((c) => {
      const v = Math.max(0, c.max_abs_sf ?? 0);
      const r =
        CONSTRAINT_R_MIN +
        (CONSTRAINT_R_MAX - CONSTRAINT_R_MIN) * Math.sqrt(v / maxVal);
      return {
        type: "Feature",
        geometry: { type: "Point", coordinates: [c.lon as number, c.lat as number] },
        properties: {
          constraint_key: c.constraint_key,
          r,
          max_abs_sf: c.max_abs_sf,
          binding_hours: c.binding_hours,
          zone_label: topZoneLabel(c.zone_shares),
          low_conf: isLowConfidence(c),
          thin: isThinSupport(c),
        },
      };
    }),
  };
}

// The dominant zone share, for the hover tooltip ("STH 62%").
function topZoneLabel(
  shares: Record<string, number> | null | undefined
): string {
  if (!shares) return "—";
  let bestZone = "";
  let bestShare = 0;
  for (const [z, s] of Object.entries(shares)) {
    if (s > bestShare) {
      bestShare = s;
      bestZone = z;
    }
  }
  if (!bestZone) return "—";
  return `${bestZone} ${Math.round(bestShare * 100)}%`;
}

// The reach dipole's axis: an arc from the export end (negative-SF nodes) to
// the import end (positive-SF nodes), each end the |SF|-weighted centroid of
// its sign. Null when the reach is one-sided (no dipole to draw).
function buildCorridorArc(
  reach: ConstraintReach
): GeoJSON.Feature<GeoJSON.LineString> | null {
  let posW = 0;
  let posLon = 0;
  let posLat = 0;
  let negW = 0;
  let negLon = 0;
  let negLat = 0;
  for (const s of reach.sps) {
    if (s.lat == null || s.lon == null) continue;
    const w = Math.abs(s.sf);
    if (s.sf >= 0) {
      posW += w;
      posLon += w * s.lon;
      posLat += w * s.lat;
    } else {
      negW += w;
      negLon += w * s.lon;
      negLat += w * s.lat;
    }
  }
  if (posW <= 0 || negW <= 0) return null;
  const a: [number, number] = [negLon / negW, negLat / negW];
  const b: [number, number] = [posLon / posW, posLat / posW];

  // Quadratic bézier with a perpendicular bulge, so the axis reads as a corridor
  // rather than a straight chord through the marker clutter.
  const mx = (a[0] + b[0]) / 2;
  const my = (a[1] + b[1]) / 2;
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const bulge = 0.18;
  const cx = mx - dy * bulge;
  const cy = my + dx * bulge;
  const n = 32;
  const coords: [number, number][] = [];
  for (let i = 0; i <= n; i++) {
    const t = i / n;
    const u = 1 - t;
    coords.push([
      u * u * a[0] + 2 * u * t * cx + t * t * b[0],
      u * u * a[1] + 2 * u * t * cy + t * t * b[1],
    ]);
  }
  return { type: "Feature", geometry: { type: "LineString", coordinates: coords }, properties: {} };
}

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
  palette: Palette;
  lmpStats: LmpStats | null;
  mcStats: ModeledCongestionStats | null;
  onSpHover: (
    spId: string | null,
    props: Record<string, unknown> | null
  ) => void;
  onSpClick: (spId: string, props: Record<string, unknown>) => void;
  onMapClick: () => void;
  selectedSpId: string | null;
  // Constraint overlay (SF structure). `constraints` null → layer absent;
  // `showConstraints` toggles visibility. Passed only to the pane that owns
  // the overlay (the left/prediction map). `highlightedConstraints` glows the
  // drivers of the clicked node; hover/click surface the layer's interactions.
  constraints?: ConstraintGeo[] | null;
  showConstraints?: boolean;
  highlightedConstraints?: Set<string>;
  onConstraintHover?: (props: Record<string, unknown> | null) => void;
  onConstraintClick?: (constraintKey: string) => void;
  // The de-piled overview (SF cores + type). When present it REPLACES the flat
  // centroid overlay: the native constraint-markers layer is torn down and the
  // SVG OverviewOverlay draws each constraint at its |SF|² core instead.
  overview?: MapOverview | null;
  // Constraint-reach mode. When set, the SP layer recolors: nodes the
  // constraint drives glow by *signed* SF (the export/import dipole), the rest
  // fade; a corridor arc traces the dipole axis. Null → normal node coloring.
  reach?: ConstraintReach | null;
  // `side` names the pane so App can namespace per-side state; `onMapReady`
  // exposes the maplibre instance so App can mirror the camera across panes.
  side?: "prediction" | "actual";
  onMapReady?: (map: maplibregl.Map) => void;
}

export default function GridMap({
  points,
  rows,
  palette,
  lmpStats,
  mcStats,
  onSpHover,
  onSpClick,
  onMapClick,
  selectedSpId,
  constraints,
  showConstraints = true,
  highlightedConstraints,
  onConstraintHover,
  onConstraintClick,
  reach,
  overview,
  onMapReady,
}: Props) {
  const prevSelectedRef = useRef<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  // The map instance as STATE (not just the ref) so the SVG OverviewOverlay child
  // mounts and re-projects the moment the map is created.
  const [mapInstance, setMapInstance] = useState<maplibregl.Map | null>(null);
  // Flipped inside the topology effect's onLoad handler after the `sps` source
  // is added. Coloring / selection effects gate on this so a remount doesn't
  // paint into a map whose source isn't ready yet — and re-fire the paint the
  // moment the source lands.
  const [sourcesReady, setSourcesReady] = useState(false);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const tooltipRef = useRef<maplibregl.Popup | null>(null);

  // Stash the latest callback props in a ref so the map setup effect can bind
  // handlers once on mount and still call the latest version of each callback.
  const callbacksRef = useRef({
    onSpHover,
    onSpClick,
    onMapClick,
    onConstraintHover,
    onConstraintClick,
  });
  useEffect(() => {
    callbacksRef.current = {
      onSpHover,
      onSpClick,
      onMapClick,
      onConstraintHover,
      onConstraintClick,
    };
  }, [onSpHover, onSpClick, onMapClick, onConstraintHover, onConstraintClick]);

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
    setMapInstance(map);
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
      setMapInstance(null);
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

      // SP circles, colored per palette via feature-state.
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
            // Faded feature-state dims nodes outside a constraint's reach.
            "circle-opacity": [
              "case",
              ["boolean", ["feature-state", "faded"], false],
              0.08,
              0.9,
            ],
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
            // Selected = a distinct, persistent white ring (thicker than hover)
            // so the active click stays visible until another node is selected
            // or the selection is cleared. Hover keeps the sky-blue ring.
            "circle-stroke-width": [
              "case",
              ["boolean", ["feature-state", "selected"], false],
              4,
              ["boolean", ["feature-state", "hovered"], false],
              2,
              0,
            ],
            "circle-stroke-color": [
              "case",
              ["boolean", ["feature-state", "selected"], false],
              "#ffffff",
              "#38bdf8",
            ],
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

  // Color SPs when rows/palette/stats change. Same $/MWh quantity → same
  // color mapping on both panes, so prediction and actual are comparable by
  // eye. With no rows loaded, clear the color feature-state so the circles
  // fall back to the base fill.
  //
  // Clearing always uses setFeatureState(..., null), never removeFeatureState:
  // a keyed delete on a feature with no committed state crashes maplibre's
  // coalesceChanges (this.state[sourceLayer][id] is undefined), and the
  // overlay/corridor addSource calls trigger that coalesce mid-batch — which
  // would blank the whole map. `reachIdsRef` tracks the nodes reach touched so
  // exiting reach un-fades exactly those.
  const reachIdsRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.getSource("sps") || !points) return;
    const fc = points as GeoJSON.FeatureCollection<
      GeoJSON.Point,
      { sp_id: string }
    >;

    // Reach mode: the clicked constraint's driven nodes glow by *signed* SF
    // (blue export end ↔ cream ↔ red import end, normalized to the reach's own
    // max |SF|); every other node fades. This is SF *structure*, deliberately
    // overriding the realized-congestion palette while a constraint is pinned.
    if (reach && reach.sps.length > 0) {
      const bySp = new Map<string, number>();
      let maxAbs = 1e-9;
      for (const s of reach.sps) {
        bySp.set(s.settlement_point, s.sf);
        maxAbs = Math.max(maxAbs, Math.abs(s.sf));
      }
      const touched = new Set<string>();
      for (const feat of fc.features) {
        const id = feat.properties.sp_id;
        const sf = bySp.get(id);
        if (sf === undefined) {
          map.setFeatureState({ source: "sps", id }, { color: null, faded: true });
        } else {
          const norm = Math.max(-1, Math.min(1, sf / maxAbs));
          map.setFeatureState(
            { source: "sps", id },
            { color: modeledCongestionColor(norm), faded: false }
          );
        }
        touched.add(id);
      }
      reachIdsRef.current = touched;
      return;
    }

    // Leaving reach mode: un-fade exactly the nodes reach touched.
    if (reachIdsRef.current.size) {
      for (const id of reachIdsRef.current) {
        map.setFeatureState({ source: "sps", id }, { faded: false });
      }
      reachIdsRef.current = new Set();
    }

    // Palette "off": no congestion/LMP fill — clear every node's color so the
    // circles fall back to the base fill and the SF overlay reads alone.
    if (palette === "off") {
      for (const feat of fc.features) {
        map.setFeatureState(
          { source: "sps", id: feat.properties.sp_id },
          { color: null }
        );
      }
      return;
    }

    if (!rows.length) {
      for (const feat of fc.features) {
        map.setFeatureState(
          { source: "sps", id: feat.properties.sp_id },
          { color: null }
        );
      }
      return;
    }

    for (const row of rows) {
      let color: string;
      if (palette === "congestion") {
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
  }, [rows, palette, lmpStats, mcStats, points, sourcesReady, reach]);

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

  // Constraint overlay: markers at each centroid, sized by max |SF|, drawn
  // above the SP circles. Only mounts when `constraints` is passed (the pane
  // that owns the overlay); a null/empty list tears the layer back down.
  const overlayBoundRef = useRef(false);
  const prevHighlightRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !sourcesReady) return;

    const apply = () => {
      // The overview REPLACES the centroid overlay: when it's present, tear the
      // native constraint-markers layer down and let OverviewOverlay draw cores.
      const hasData = !!constraints && constraints.length > 0 && !overview;

      if (!hasData) {
        if (map.getLayer("constraint-markers"))
          map.removeLayer("constraint-markers");
        if (map.getSource("constraints")) map.removeSource("constraints");
        overlayBoundRef.current = false;
        return;
      }

      const fc = buildConstraintFC(constraints as ConstraintGeo[]);

      const src = map.getSource("constraints") as
        | maplibregl.GeoJSONSource
        | undefined;
      if (src) {
        src.setData(fc);
      } else {
        map.addSource("constraints", {
          type: "geojson",
          data: fc,
          promoteId: "constraint_key",
        });
      }

      if (!map.getLayer("constraint-markers")) {
        map.addLayer({
          id: "constraint-markers",
          type: "circle",
          source: "constraints",
          paint: {
            "circle-radius": [
              "interpolate",
              ["linear"],
              ["zoom"],
              4,
              ["*", ["get", "r"], 0.55],
              10,
              ["get", "r"],
            ],
            "circle-color": [
              "case",
              ["boolean", ["feature-state", "highlighted"], false],
              CONSTRAINT_FILL_HI,
              ["boolean", ["get", "low_conf"], false],
              CONSTRAINT_FILL_LOW,
              CONSTRAINT_FILL,
            ],
            "circle-stroke-color": [
              "case",
              ["boolean", ["get", "low_conf"], false],
              CONSTRAINT_STROKE_LOW,
              CONSTRAINT_STROKE,
            ],
            "circle-stroke-width": [
              "case",
              ["boolean", ["feature-state", "highlighted"], false],
              2.5,
              ["boolean", ["feature-state", "hovered"], false],
              1.5,
              0.75,
            ],
            "circle-stroke-opacity": 0.9,
          },
        });
      }

      // Bind hover/click once per layer instance.
      if (!overlayBoundRef.current) {
        let hoveredId: string | null = null;
        const setHover = (id: string | null, on: boolean) => {
          if (id == null) return;
          map.setFeatureState(
            { source: "constraints", id },
            { hovered: on }
          );
        };
        map.on("mousemove", "constraint-markers", (e) => {
          if (!e.features?.length) return;
          map.getCanvas().style.cursor = "pointer";
          const props = e.features[0].properties as Record<string, unknown>;
          const id = props.constraint_key as string;
          if (hoveredId !== id) {
            setHover(hoveredId, false);
            hoveredId = id;
            setHover(hoveredId, true);
          }
          callbacksRef.current.onConstraintHover?.(props);
          tooltipRef.current
            ?.setLngLat(e.lngLat)
            .setHTML(
              `<div class="tip-id tip-id--constraint">${props.constraint_key}</div>
               <div class="tip-zone">${props.zone_label ?? "—"} · ${
                props.binding_hours ?? "—"
              } binding h</div>${
                props.low_conf
                  ? `<div class="tip-lowconf">⚠ low confidence — ridge clamp</div>`
                  : props.thin
                  ? `<div class="tip-thin">thin support — few binding hours</div>`
                  : ""
              }`
            )
            .addTo(map);
        });
        map.on("mouseleave", "constraint-markers", () => {
          map.getCanvas().style.cursor = "";
          setHover(hoveredId, false);
          hoveredId = null;
          callbacksRef.current.onConstraintHover?.(null);
          tooltipRef.current?.remove();
        });
        map.on("click", "constraint-markers", (e) => {
          if (!e.features?.length) return;
          e.preventDefault?.();
          const props = e.features[0].properties as Record<string, unknown>;
          callbacksRef.current.onConstraintClick?.(
            props.constraint_key as string
          );
        });
        overlayBoundRef.current = true;
      }

      // Visibility toggle.
      map.setLayoutProperty(
        "constraint-markers",
        "visibility",
        showConstraints ? "visible" : "none"
      );

      // While a constraint is pinned (reach mode), fade the overlay hard so its
      // bubbles stop hiding the nodes lighting up beneath them — otherwise most
      // clicks land under a marker and the reach is invisible. The layer stays
      // present (faintly) so you can still hop between constraints.
      const dimmed = !!reach;
      map.setPaintProperty(
        "constraint-markers",
        "circle-opacity",
        dimmed ? 0.1 : 1
      );
      map.setPaintProperty(
        "constraint-markers",
        "circle-stroke-opacity",
        dimmed ? 0.12 : 0.9
      );

      // Highlight the clicked node's drivers (Commit C wires the source).
      const next = highlightedConstraints ?? new Set<string>();
      for (const id of prevHighlightRef.current) {
        if (!next.has(id))
          map.setFeatureState(
            { source: "constraints", id },
            { highlighted: false }
          );
      }
      for (const id of next) {
        map.setFeatureState(
          { source: "constraints", id },
          { highlighted: true }
        );
      }
      prevHighlightRef.current = next;
    };

    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [constraints, showConstraints, highlightedConstraints, reach, overview, sourcesReady]);

  // Reach corridor arc: the dipole axis between the constraint's export- and
  // import-end centroids. Drawn beneath the SP circles so it reads as ground,
  // not a marker. Absent reach (or a one-sided reach) tears the arc down.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !sourcesReady) return;

    const apply = () => {
      const arc = reach ? buildCorridorArc(reach) : null;

      if (!arc) {
        if (map.getLayer("reach-corridor")) map.removeLayer("reach-corridor");
        if (map.getSource("reach-corridor")) map.removeSource("reach-corridor");
        return;
      }

      const src = map.getSource("reach-corridor") as
        | maplibregl.GeoJSONSource
        | undefined;
      if (src) {
        src.setData(arc);
      } else {
        map.addSource("reach-corridor", { type: "geojson", data: arc });
      }

      if (!map.getLayer("reach-corridor")) {
        // Beneath the SP circles (insert before "sps") so nodes stay on top.
        map.addLayer(
          {
            id: "reach-corridor",
            type: "line",
            source: "reach-corridor",
            layout: { "line-cap": "round" },
            paint: {
              "line-color": CONSTRAINT_STROKE,
              "line-width": 1.6,
              "line-opacity": 0.5,
              "line-dasharray": [2, 2],
            },
          },
          map.getLayer("sps") ? "sps" : undefined
        );
      }
    };

    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [reach, sourcesReady]);

  return (
    <>
      <div
        ref={containerRef}
        style={{ width: "100%", height: "100%", position: "relative" }}
      >
        <OverviewOverlay
          map={mapInstance}
          overview={overview ?? null}
          visible={showConstraints}
        />
      </div>
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
        .tip-id--constraint { color: #c4b5fd; }
        .tip-zone { color: #8899aa; font-size: 10px; margin-top: 2px; }
        .tip-lowconf { color: #94a3b8; font-size: 10px; margin-top: 3px; }
        .tip-thin { color: #a8a29e; font-size: 10px; margin-top: 3px; }
      `}</style>
    </>
  );
}
