import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type {
  SpRow,
  Palette,
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
  normalizeLmpFromStats,
  modeledCongestionColor,
  normalizeModeledCongestion,
  type LmpStats,
  type ModeledCongestionStats,
} from "../../lib/colors";
import { cssVar, onThemeChange, useTheme, type Theme } from "../../lib/theme";

// Map chrome resolved from the --map-* / theme tokens in index.css. maplibre
// paint properties cannot take var(), so the values are read out of the computed
// root style and re-applied whenever the theme flips (see the effect below).
function chromeColors() {
  return {
    label: cssVar("--map-label"),
    halo: cssVar("--map-halo"),
    outline: cssVar("--map-outline"),
    outlineFill: cssVar("--map-outline-fill"),
    nodeNull: cssVar("--map-node-null"),
    nodeHover: cssVar("--map-node-hover"),
    accent: cssVar("--accent"),
    // Reach-corridor stroke for the dipole arc. The flat centroid "constraint
    // pile" overlay was retired in favor of native overview marks (MST corridors,
    // GTC interface axes, and radial rings); this hue survives for the arc.
    constraint: cssVar("--violet"),
  };
}

// The reach dipole's axis: an arc between the import end (negative-SF nodes) and
// the export end (positive-SF nodes), each end the |SF|-weighted centroid of
// its sign (docs/SF.md). Null when the reach is one-sided (no dipole to draw).
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
  return {
    type: "Feature",
    geometry: { type: "LineString", coordinates: coords },
    properties: {},
  };
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
  // `showConstraints` toggles the constraint layer's visibility (the header's
  // constraints toggle). Passed only to the pane that owns the overlay (the
  // left/prediction map).
  showConstraints?: boolean;
  // The de-piled overview (typed marks) — the sole constraint presentation, drawn
  // as native maplibre layers here (GTC interface axes, MST corridor lines, radial
  // rings) beneath the `sps` layer. The old flat centroid marker pile
  // (/map/constraints) it replaced has been retired.
  overview?: MapOverview | null;
  // Synced isolation (plan/0103 Group 4). `isolatedConstraint` is a constraint the
  // side-panel is hovering — it isolates that mark on the overview. `onIsolateConstraint`
  // reports the overview's OWN hover back so the panel row highlights in step.
  // `isolatedConstraint` filters the overview mark layers to a single constraint
  // (the side-panel row being hovered). `onIsolateConstraint` reports/loads a
  // constraint's focus — driven by the multi-constraint popover rows here.
  isolatedConstraint?: string | null;
  onIsolateConstraint?: (id: string | null) => void;
  // Focus reach (plan/0103): the dipole SP-coloring for a hovered/locked constraint
  // — its constituent nodes glow signed import/export, every other node fades to the
  // no-data fill. Distinct from `reach` (the click/DetailCard node-explorer) so a
  // hover doesn't open that card; it just recolors the SP layer.
  focusReach?: ConstraintReach | null;
  // A settlement point to ring white — the member node hovered in the panel's
  // constituent list, so the panel row and the map node point at each other.
  ringedSpId?: string | null;
  // Multi-constraint popover rows (plan/0112): hover previews that constraint in
  // the DetailCard, click pins it. Node hover/click itself rides the base `sps`
  // layer (onSpHover/onSpClick) — the overview no longer intercepts it.
  onConstraintPreview?: (key: string | null) => void;
  onConstraintSelect?: (key: string) => void;
  // Constraint-reach mode. When set, the SP layer recolors: nodes the
  // constraint drives glow by *signed* SF (the export/import dipole), the rest
  // fade; a corridor arc traces the dipole axis. Null → normal node coloring.
  reach?: ConstraintReach | null;
  // `side` names the pane so App can namespace per-side state; `onMapReady`
  // exposes the maplibre instance so App can mirror the camera across panes.
  side?: "prediction" | "actual";
  onMapReady?: (map: maplibregl.Map) => void;
  // The diverging color ramp for the `congestion` palette. Defaults to the
  // blue↔red congestion ramp; the forecast-error view passes `forecastErrorColor`
  // (emerald↔magenta) so the error reads on its own hue axis. Only affects node
  // fill — the reach/SF glow stays on modeledCongestionColor (there the sign is the
  // export/import dipole).
  congestionColor?: (norm: number, theme: Theme) => string;
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
  congestionColor = modeledCongestionColor,
}: Props) {
  // Node fill colors flip with the theme (light gets a visible grey center — see
  // lib/colors.ts). Subscribing here re-runs the color effect below on a flip.
  const theme = useTheme();
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
  const callbacksRef = useRef({
    onSpHover,
    onSpClick,
    onMapClick,
  });
  useEffect(() => {
    callbacksRef.current = {
      onSpHover,
      onSpClick,
      onMapClick,
    };
  }, [onSpHover, onSpClick, onMapClick]);

  // Multi-constraint hover box (plan/0112). `spMembers` maps sp_id → the overview
  // constraints it belongs to; the base `sps` hover opens the box for a 2+ node,
  // anchored at the node's pixel. Kept in a ref too so the once-bound `sps`
  // handler reads the latest map without rebinding.
  const [popover, setPopover] = useState<{
    sp: string;
    members: OvMember[];
    x: number;
    y: number;
  } | null>(null);
  const spMembers = useMemo(() => buildSpMembers(overview ?? null), [overview]);
  const spMembersRef = useRef(spMembers);
  useEffect(() => {
    spMembersRef.current = spMembers;
  }, [spMembers]);
  // The overlay is unmounted when the constraint layer is off, so drop any box.
  useEffect(() => {
    if (!showConstraints) setPopover(null);
  }, [showConstraints]);

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

  // Repaint map chrome when the theme flips. CSS custom properties cascade to
  // stylesheet rules on their own, but maplibre paint properties are baked in at
  // addLayer() time, so every --map-* dependent value has to be pushed again.
  // Data colors are untouched: lib/colors.ts anchors are shared across themes.
  useEffect(() => {
    return onThemeChange(() => {
      const map = mapRef.current;
      if (!map || !map.isStyleLoaded()) return;
      const c = chromeColors();

      // Layers are added conditionally (constraints overlay, reach arc), so
      // guard each one rather than assuming the full set exists.
      const set = (layer: string, prop: string, value: unknown) => {
        if (map.getLayer(layer)) map.setPaintProperty(layer, prop, value);
      };

      set("texas-fill", "fill-color", c.outlineFill);
      set("texas-line", "line-color", c.outline);
      set("city-labels", "text-color", c.label);
      set("city-labels", "text-halo-color", c.halo);
      set("reach-corridor", "line-color", c.constraint);
      set("sps", "circle-stroke-color", [
        "case",
        ["boolean", ["feature-state", "selected"], false],
        c.nodeHover,
        ["boolean", ["feature-state", "ringed"], false],
        c.nodeHover,
        c.accent,
      ]);
      // The null-data fallback is the second branch of the circle-color case.
      set("sps", "circle-color", [
        "case",
        ["!=", ["feature-state", "color"], null],
        ["feature-state", "color"],
        c.nodeNull,
      ]);
    });
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

      const chrome = chromeColors();

      // Texas state boundary. The map has no basemap, so this is the only
      // geographic reference besides the city labels; it is drawn first and
      // therefore sits beneath everything else.
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
            "text-color": chrome.label,
            "text-halo-color": chrome.halo,
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
              chrome.nodeNull,
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
              3,
              8,
              5.5,
              12,
              9,
            ],
            // Selected = a distinct, persistent high-contrast ring (thicker than
            // hover) so the active click stays visible until another node is
            // selected or the selection is cleared. Hover keeps the sky-blue
            // ring. The ring color inverts with the theme -- white over the dark
            // ground, near-black over the light one.
            "circle-stroke-width": [
              "case",
              ["boolean", ["feature-state", "selected"], false],
              4,
              // `ringed` = a member node hovered in the panel's constituent list.
              ["boolean", ["feature-state", "ringed"], false],
              3,
              ["boolean", ["feature-state", "hovered"], false],
              2,
              0,
            ],
            "circle-stroke-color": [
              "case",
              ["boolean", ["feature-state", "selected"], false],
              chrome.nodeHover,
              ["boolean", ["feature-state", "ringed"], false],
              chrome.nodeHover,
              chrome.accent,
            ],
            // The ring must read even over a faded (non-member) node.
            "circle-stroke-opacity": 1,
          },
        });
      }

      // Hover interactions
      map.on("mousemove", "sps", (e) => {
        if (!e.features?.length) return;
        map.getCanvas().style.cursor = "crosshair";
        const props = e.features[0].properties as Record<string, unknown>;
        const sp = props.sp_id as string;
        callbacksRef.current.onSpHover(sp, props);
        tooltipRef.current
          ?.setLngLat(e.lngLat)
          .setHTML(
            `<div class="tip-id">${props.sp_id}</div>
             <div class="tip-zone">${props.load_zone ?? "—"}</div>`
          )
          .addTo(map);

        // Multi-constraint node → open the constraint box, anchored at the node's
        // pixel (not the cursor, so it stays put). A 0-1 node closes any open box.
        const mem = spMembersRef.current.get(sp);
        if (mem && mem.length >= 2) {
          const geom = e.features[0].geometry as GeoJSON.Point;
          const pt = map.project(geom.coordinates as [number, number]);
          setPopover({ sp, members: mem, x: pt.x, y: pt.y });
        } else {
          setPopover(null);
        }
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

    // Click on empty map → clear pinned + close the constraint box
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

    // Reach mode: a focused constraint's driven nodes glow by *signed* SF (red
    // import end SF<0 ↔ cream ↔ blue export end SF>0, normalized to the reach's own
    // max |SF|; docs/SF.md). Colored by congestion sign (−SF), so the glow agrees
    // with the congestion fill: import is red, export is blue.
    // Every other node fades to the no-data fill. This is SF *structure*,
    // deliberately overriding the realized/forecast-error palette while a
    // constraint is focused. `focusReach` (the effective hovered/locked constraint)
    // wins over the DetailCard's own `reach`, so the node glow always tracks the
    // SAME constraint the marks isolate — hovering a panel row lights ITS nodes,
    // not whichever one the card happens to have pinned (plan/0112).
    const rch = focusReach ?? reach;
    if (rch && rch.sps.length > 0) {
      const bySp = new Map<string, number>();
      let maxAbs = 1e-9;
      for (const s of rch.sps) {
        bySp.set(s.settlement_point, s.sf);
        maxAbs = Math.max(maxAbs, Math.abs(s.sf));
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
          // Color by congestion sign (−SF): import (SF<0) → +norm → red, export
          // (SF>0) → −norm → blue, so the glow agrees with the congestion fill.
          const norm = Math.max(-1, Math.min(1, -sf / maxAbs));
          map.setFeatureState(
            { source: "sps", id },
            { color: modeledCongestionColor(norm, theme), faded: false }
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
          ? congestionColor(
              normalizeModeledCongestion(row.congestion, mcStats),
              theme
            )
          : congestionColor(0, theme);
      } else {
        color = lmpStats
          ? lmpColor(normalizeLmpFromStats(row.spp, lmpStats), theme)
          : lmpColor(0.5, theme);
      }
      map.setFeatureState({ source: "sps", id: row.sp_id }, { color });
    }
  }, [
    rows,
    palette,
    lmpStats,
    mcStats,
    points,
    sourcesReady,
    reach,
    focusReach,
    congestionColor,
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

  // Ringed SP — the member node hovered in the panel's constituent list. A white
  // ring on the corresponding map node, cleared when the hover moves off.
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
              "line-color": chromeColors().constraint,
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

  // Overview mark layers: GTCs are signed-axis gate glyphs, transmission is
  // MST corridors, and radials are rings. All draw beneath `sps` so node clicks
  // stay on the base layer. Empty sources when off; `isolatedConstraint` filters
  // every mark to a single constraint.
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

      // Theme refresh + isolation filter, applied every pass. Use an explicit
      // all-pass filter (`["all"]`) rather than clearing with null — clearing to
      // null was intermittently leaving every mark hidden when un-isolating.
      map.setPaintProperty("ov-gtc-axis", "line-color", sf.gtc);
      map.setPaintProperty("ov-gtc-gate", "line-color", sf.gtc);
      map.setPaintProperty("ov-corridor", "line-color", sf.transmission);
      map.setPaintProperty("ov-corridor", "line-opacity", sf.lineOpacity);
      map.setPaintProperty("ov-radial", "circle-stroke-color", sf.radial);
      const filt = (
        isolatedConstraint
          ? ["==", ["get", "constraint_key"], isolatedConstraint]
          : ["all"]
      ) as maplibregl.FilterSpecification;
      for (const id of ["ov-gtc-axis", "ov-gtc-gate", "ov-radial"])
        map.setFilter(id, filt);
      map.setFilter("ov-corridor", filt);
    };

    // `sourcesReady` already implies the style is loaded (it flips inside the
    // topology onLoad), so apply directly — deferring to a `once("load")` that has
    // already fired would strand the update and leave marks in a stale state.
    apply();
    // `selectedSpId`/`reach`/`focusReach` are here so the marks re-assert (setData
    // + re-add any missing layer + re-filter) after any node/constraint interaction
    // — they can never be left stranded by another effect touching the style.
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

  const containerWidth = containerRef.current?.clientWidth ?? 0;

  return (
    <>
      <div
        ref={containerRef}
        style={{ width: "100%", height: "100%", position: "relative" }}
      >
        {popover && (
          <OverviewPopover
            sp={popover.sp}
            members={popover.members}
            x={popover.x}
            y={popover.y}
            containerWidth={containerWidth}
            onRowHover={(key) => {
              onIsolateConstraint?.(key);
              onConstraintPreview?.(key);
            }}
            onRowClick={(key) => {
              // Commit + dismiss the box. Leaving it open lets the mouse graze
              // other rows on the way out, and a row-hover unlocks the focus we
              // just locked — so close it here and the lock holds.
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
        /* Chrome matched to the shared .tt tooltip (index.css): glass surface,
           bright border, panel shadow — so the map's feature-hover popup reads as
           the same tooltip system, even though maplibre owns its positioning. */
        .grid-tooltip .maplibregl-popup-content {
          background: var(--bg-glass);
          border: 1px solid var(--border-bright);
          box-shadow: var(--shadow-panel);
          border-radius: 4px;
          padding: 8px 10px;
          color: var(--text-primary);
          font-family: var(--font-mono);
          font-size: var(--fs-body);
          pointer-events: none;
        }
        .grid-tooltip .maplibregl-popup-tip { display: none; }
        .tip-id { color: var(--accent); font-size: var(--fs-body); }
        .tip-id--constraint { color: var(--violet); }
        .tip-zone { color: var(--text-secondary); font-size: var(--fs-label); margin-top: 2px; }
        .tip-lowconf { color: var(--text-dim); font-size: var(--fs-label); margin-top: 3px; }
        .tip-thin { color: var(--text-faint); font-size: var(--fs-label); margin-top: 3px; }
      `}</style>
    </>
  );
}
