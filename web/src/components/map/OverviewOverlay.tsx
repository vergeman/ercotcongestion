import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type maplibregl from "maplibre-gl";
import type { MapOverview, OverviewConstraint, ReachSp } from "../../api/types";

// The de-piled overview, drawn as an SVG overlay pinned over the maplibre canvas
// (plan/0092-0003). This is a faithful port of the hybrid-v4 spike
// (plan/0092-map-revizualization/spike/build_hybrid4.py): each constraint is
// drawn at its |SF|²-core with a mark whose FORM matches its type, and the whole
// thing is interactive — hover a core to isolate its constraint, hover a
// settlement point to open a cursor popover of every constraint it belongs to.
//
// Why SVG-over-canvas and not a native maplibre layer: the GTC metaball needs an
// SVG goo filter (feGaussianBlur + alpha threshold) and every mark needs
// per-element hit-testing — neither is expressible in maplibre's WebGL layers.
// The basemap + SP layer stay beneath in WebGL; this overlay projects each
// lat/lon with map.project() and re-draws on every camera move.

// Type hues. Blue↔red is RESERVED for the signed source/sink drill-down, so the
// overview picks non-reserved categorical hues (design-notes/type-coloring-and-sign):
//   gtc          amber  — a region (metaball) it holds
//   transmission violet — a corridor (MST) it runs along
//   radial       teal   — a single point
const COL: Record<string, string> = {
  gtc: "#e0a83a",
  transmission: "#a78bfa",
  radial: "#2dd4bf",
};
const UNTYPED = "#94a3b8"; // slate: located but no type verdict
// Draw order: gtc regions on the bottom, radial points on top.
const RANK: Record<string, number> = { gtc: 0, transmission: 1, radial: 2 };

// Corridor edges longer than this are dropped — a stylized transmission run
// shouldn't leap across the whole state between two weakly-related nodes.
const MAX_CORRIDOR_KM = 150;

function haversineKm(
  aLat: number,
  aLon: number,
  bLat: number,
  bLon: number
): number {
  const R = 6371;
  const dLat = ((bLat - aLat) * Math.PI) / 180;
  const dLon = ((bLon - aLon) * Math.PI) / 180;
  const la1 = (aLat * Math.PI) / 180;
  const la2 = (bLat * Math.PI) / 180;
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(la1) * Math.cos(la2) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(Math.min(1, h)));
}

// Prim's MST over haversine distance (port of mst_spike.mst_edges). Returns
// (i, j) index pairs into `nodes` — the skeleton the GTC/transmission marks draw.
function mstEdges(nodes: ReachSp[]): [number, number][] {
  const n = nodes.length;
  if (n < 2) return [];
  const inTree = new Array(n).fill(false);
  const best = new Array(n).fill(Infinity);
  const parent = new Array(n).fill(0);
  inTree[0] = true;
  for (let k = 0; k < n; k++)
    best[k] = haversineKm(
      nodes[0].lat as number,
      nodes[0].lon as number,
      nodes[k].lat as number,
      nodes[k].lon as number
    );
  const edges: [number, number][] = [];
  for (let step = 0; step < n - 1; step++) {
    let j = -1;
    let bd = Infinity;
    for (let k = 0; k < n; k++)
      if (!inTree[k] && best[k] < bd) {
        bd = best[k];
        j = k;
      }
    if (j < 0) break;
    inTree[j] = true;
    edges.push([parent[j], j]);
    for (let k = 0; k < n; k++) {
      if (inTree[k]) continue;
      const d = haversineKm(
        nodes[j].lat as number,
        nodes[j].lon as number,
        nodes[k].lat as number,
        nodes[k].lon as number
      );
      if (d < best[k]) {
        best[k] = d;
        parent[k] = j;
      }
    }
  }
  return edges;
}

interface Member {
  key: string;
  type: string;
  sf: number;
  bh: number | null;
}
interface NodeAgg {
  sp: string;
  lat: number;
  lon: number;
  members: Member[];
}
interface Prepared {
  c: OverviewConstraint;
  nodes: ReachSp[]; // located subset
  edges: [number, number][];
  nmax: number;
}

interface Props {
  map: maplibregl.Map | null;
  overview: MapOverview | null;
  // Overlay visibility — driven by the header's constraints toggle. When false
  // the whole SVG overlay is unmounted, so "off" actually hides the cores/marks
  // (the overview REPLACES the native marker layer, which `showConstraints`
  // alone can no longer reach).
  visible?: boolean;
}

export default function OverviewOverlay({
  map,
  overview,
  visible = true,
}: Props) {
  // Isolation + pin + popover state. `isoKey` dims every other constraint;
  // `pinned` freezes the current isolation (set by clicking a popover row) so
  // moving the mouse away doesn't clear it; `popNi` is the node whose membership
  // popover is open (index into `model.nodes`).
  const [isoKey, setIsoKey] = useState<string | null>(null);
  const [pinned, setPinned] = useState(false);
  const [popNi, setPopNi] = useState<number | null>(null);
  // Bumped on every camera change so projection re-runs in render.
  const [, setTick] = useState(0);
  // Mirror `pinned` into a ref for the once-bound map listeners below.
  const pinnedRef = useRef(false);
  useEffect(() => {
    pinnedRef.current = pinned;
  }, [pinned]);

  useEffect(() => {
    if (!map) return;
    const rerender = () => setTick((t) => (t + 1) % 1_000_000);
    map.on("move", rerender);
    map.on("zoom", rerender);
    map.on("resize", rerender);
    // Clicking empty map clears the pin + isolation + popover (the goo/marks and
    // the node dots swallow their own clicks, so this only fires on bare canvas).
    const clearPin = () => {
      setPinned(false);
      setIsoKey(null);
      setPopNi(null);
    };
    map.on("click", clearPin);
    // Leaving the map entirely clears a *transient* (un-pinned) hover.
    const cont = map.getContainer();
    const onLeave = () => {
      if (pinnedRef.current) return;
      setIsoKey(null);
      setPopNi(null);
    };
    cont.addEventListener("mouseleave", onLeave);
    return () => {
      map.off("move", rerender);
      map.off("zoom", rerender);
      map.off("resize", rerender);
      map.off("click", clearPin);
      cont.removeEventListener("mouseleave", onLeave);
    };
  }, [map]);

  // Camera-independent structure: order constraints, compute each MST, and build
  // the deduplicated node → membership index. Recomputed only when the payload
  // changes, not on pan/zoom.
  const model = useMemo(() => {
    if (!overview) return null;
    const cons = overview.constraints.filter(
      (c) => c.core_lat != null && c.core_lon != null
    );
    const kmax = Math.max(1, ...cons.map((c) => c.binding_hours ?? 0));
    const ordered = [...cons].sort(
      (a, b) =>
        (RANK[a.ctype ?? ""] ?? 1) - (RANK[b.ctype ?? ""] ?? 1) ||
        (a.binding_hours ?? 0) - (b.binding_hours ?? 0)
    );
    const prepared: Prepared[] = ordered.map((c) => {
      const nodes = c.nodes.filter((n) => n.lat != null && n.lon != null);
      return {
        c,
        nodes,
        edges: mstEdges(nodes),
        nmax: Math.max(1e-9, ...nodes.map((n) => Math.abs(n.sf))),
      };
    });
    const nodemap = new Map<string, NodeAgg>();
    for (const { c, nodes } of prepared) {
      for (const n of nodes) {
        let nd = nodemap.get(n.settlement_point);
        if (!nd) {
          nd = {
            sp: n.settlement_point,
            lat: n.lat as number,
            lon: n.lon as number,
            members: [],
          };
          nodemap.set(n.settlement_point, nd);
        }
        nd.members.push({
          key: c.constraint_key,
          type: c.ctype ?? "",
          sf: n.sf,
          bh: c.binding_hours,
        });
      }
    }
    const nodes = [...nodemap.values()];
    for (const nd of nodes)
      nd.members.sort((a, b) => Math.abs(b.sf) - Math.abs(a.sf));
    return { kmax, prepared, nodes };
  }, [overview]);

  if (!map || !model || !visible) return null;

  const project = (lat: number, lon: number) => map.project([lon, lat]);

  // --- structure marks (metaball / corridor / point) + hit targets -----------
  const groups = model.prepared.map(({ c, nodes, edges, nmax }) => {
    const col = COL[c.ctype ?? ""] ?? UNTYPED;
    const t = Math.sqrt((c.binding_hours ?? 0) / model.kmax); // severity 0..1
    const pts = nodes.map((n) => project(n.lat as number, n.lon as number));
    const core = project(c.core_lat as number, c.core_lon as number);
    const iso = c.constraint_key === isoKey;

    const inner: ReactNode[] = [];
    if (c.ctype === "gtc") {
      // Metaball region: one blob per node, merged by the goo filter into the
      // area the interface holds. Blob size ∝ √|SF| so the dominant lobe swells.
      inner.push(
        <g key="shadow" className="ov-shadow" filter="url(#ov-goo)" fill={col}>
          {pts.map((p, i) => (
            <circle
              key={i}
              cx={p.x}
              cy={p.y}
              r={7 + 9 * Math.sqrt(Math.abs(nodes[i].sf) / nmax)}
            />
          ))}
        </g>
      );
      inner.push(
        <g key="skel" className="ov-skel" stroke={col}>
          {edges.map(([i, j], e) => (
            <line
              key={e}
              x1={pts[i].x}
              y1={pts[i].y}
              x2={pts[j].x}
              y2={pts[j].y}
            />
          ))}
        </g>
      );
      inner.push(
        <circle
          key="core"
          className="ov-core"
          cx={core.x}
          cy={core.y}
          r={3.5 + 3.5 * t}
          fill={col}
        />
      );
    } else if (c.ctype === "radial") {
      // A single point — hollow ring, no body.
      inner.push(
        <circle
          key="core"
          className="ov-core"
          cx={core.x}
          cy={core.y}
          r={3.5 + 3 * t}
          fill="none"
          stroke={col}
          strokeWidth={2}
        />
      );
    } else {
      // Transmission corridor: the MST as a run of lines, dropping any edge
      // longer than MAX_CORRIDOR_KM.
      inner.push(
        <g
          key="skel"
          className="ov-skel ov-corridor"
          stroke={col}
          strokeWidth={0.8 + 1.8 * t}
        >
          {edges
            .filter(
              ([i, j]) =>
                haversineKm(
                  nodes[i].lat as number,
                  nodes[i].lon as number,
                  nodes[j].lat as number,
                  nodes[j].lon as number
                ) <= MAX_CORRIDOR_KM
            )
            .map(([i, j], e) => (
              <line
                key={e}
                x1={pts[i].x}
                y1={pts[i].y}
                x2={pts[j].x}
                y2={pts[j].y}
              />
            ))}
        </g>
      );
      inner.push(
        <circle
          key="core"
          className="ov-core"
          cx={core.x}
          cy={core.y}
          r={3 + 2.5 * t}
          fill={col}
        />
      );
    }

    return (
      <g
        key={c.constraint_key}
        className={`ov-con${iso ? " ov-iso" : ""}`}
      >
        {inner}
        <circle
          className="ov-hit"
          cx={core.x}
          cy={core.y}
          r={12}
          fill="#000"
          fillOpacity={0}
          onMouseEnter={() => {
            if (!pinned) setIsoKey(c.constraint_key);
          }}
        />
      </g>
    );
  });

  // --- deduplicated interactive node layer -----------------------------------
  const nodeDots = model.nodes.map((nd, i) => {
    const p = project(nd.lat, nd.lon);
    return (
      <circle
        key={nd.sp}
        className="ov-node"
        cx={p.x}
        cy={p.y}
        r={3.2}
        onMouseEnter={() => {
          if (!pinned) setPopNi(i);
        }}
      />
    );
  });

  // --- membership popover, positioned at the hovered node --------------------
  let popover: ReactNode = null;
  if (popNi != null && model.nodes[popNi]) {
    const nd = model.nodes[popNi];
    const p = project(nd.lat, nd.lon);
    const contW = map.getContainer().clientWidth;
    const flip = p.x > contW - 300;
    const left = flip ? p.x - 300 : p.x + 12;
    const top = p.y + 12;
    const shown = nd.members.slice(0, 10);
    popover = (
      <div className="ov-pop" style={{ left, top }}>
        <div className="ov-pop-sp">
          {nd.sp}{" "}
          <small>
            · {nd.members.length} constraint{nd.members.length > 1 ? "s" : ""}
          </small>
        </div>
        {shown.map((m) => {
          const src = m.sf < 0;
          return (
            <div
              key={m.key}
              className="ov-row"
              onMouseEnter={() => setIsoKey(m.key)}
              onClick={() => {
                setPinned(true);
                setIsoKey(m.key);
              }}
            >
              <span
                className="ov-chip"
                style={{ background: COL[m.type] ?? UNTYPED }}
              />
              <span className="ov-ck">{m.key}</span>
              <span className={`ov-role ${src ? "ov-src" : "ov-snk"}`}>
                {src ? "src" : "snk"} {m.sf.toFixed(2)}
              </span>
              <span className="ov-bh">{m.bh ?? "—"}h</span>
            </div>
          );
        })}
        {nd.members.length > 10 && (
          <div className="ov-more">+{nd.members.length - 10} more</div>
        )}
      </div>
    );
  }

  return (
    <>
      <svg
        className={`overview-overlay${isoKey ? " ov-dim" : ""}`}
        style={{
          position: "absolute",
          inset: 0,
          width: "100%",
          height: "100%",
          pointerEvents: "none", // only .ov-hit / .ov-node opt back in (CSS)
        }}
      >
        <defs>
          <filter id="ov-goo" x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="6" result="b" />
            <feColorMatrix
              in="b"
              mode="matrix"
              values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 20 -9"
            />
          </filter>
        </defs>
        <g className="ov-struct">{groups}</g>
        <g className="ov-nodes">{nodeDots}</g>
      </svg>
      {popover}
      <style>{`
        .overview-overlay .ov-hit, .overview-overlay .ov-node { pointer-events: auto; }
        .overview-overlay .ov-shadow { opacity: .32; }
        .overview-overlay .ov-skel line { stroke-opacity: .2; stroke-width: .8; }
        .overview-overlay .ov-corridor line { stroke-opacity: .65; }
        .overview-overlay .ov-core { stroke: #0a0d12; stroke-width: 1; pointer-events: none; }
        .overview-overlay .ov-hit { cursor: pointer; }
        .overview-overlay .ov-node { fill: #c9d3df; fill-opacity: .5; stroke: #0a0d12; stroke-width: .5; cursor: pointer; }
        .overview-overlay .ov-node:hover { fill: #fff; fill-opacity: 1; stroke: #38bdf8; stroke-width: 1.4; }
        .overview-overlay .ov-con { transition: opacity .12s; }
        .overview-overlay.ov-dim .ov-con:not(.ov-iso) { opacity: .06; }
        .overview-overlay.ov-dim .ov-node { fill-opacity: .15; }
        .overview-overlay .ov-iso .ov-shadow { opacity: .72; }
        .overview-overlay .ov-iso .ov-skel line { stroke-opacity: .9; stroke-width: 1.6; }
        .overview-overlay .ov-iso .ov-core { stroke: #fff; stroke-width: 1.6; }
        .ov-pop { position: absolute; pointer-events: auto; background: #0f1217f2;
          border: 1px solid #2b3442; border-radius: 7px; padding: 6px; font-size: 11.5px;
          min-width: 210px; max-width: 290px; box-shadow: 0 6px 22px #000a; z-index: 5; }
        .ov-pop-sp { font-family: 'Space Mono', ui-monospace, monospace; font-weight: 600;
          font-size: 11.5px; padding: 2px 5px 6px; color: #e2e8f0;
          border-bottom: 1px solid #222b36; margin-bottom: 4px; }
        .ov-pop-sp small { color: #8899aa; font-weight: 400; }
        .ov-row { display: flex; align-items: center; gap: 7px; padding: 4px 5px;
          border-radius: 4px; cursor: pointer; }
        .ov-row:hover { background: #1b2431; }
        .ov-chip { width: 8px; height: 8px; border-radius: 2px; flex: 0 0 auto; }
        .ov-ck { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
          font-family: 'Space Mono', ui-monospace, monospace; font-size: 10.5px; }
        .ov-role { font-weight: 700; font-size: 10.5px; }
        .ov-src { color: #3b82f6; } .ov-snk { color: #ef4444; }
        .ov-bh { color: #8899aa; font-size: 10px; width: 34px; text-align: right; }
        .ov-more { color: #8899aa; font-size: 10px; text-align: center; padding: 3px; }
      `}</style>
    </>
  );
}
