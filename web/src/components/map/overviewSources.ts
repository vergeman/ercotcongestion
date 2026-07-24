// Overview → maplibre GeoJSON sources (plan/0112). The de-piled constraint
// overview is drawn as NATIVE maplibre layers instead of an SVG overlay: a soft
// blended circle cloud for GTC regions, MST corridor lines for transmission, a
// ring for radials. Node interaction rides the base `sps` layer, so overview
// nodes behave exactly like every other settlement point (the SVG overlay's
// pointer-events fight with the canvas was the whole source of the click bugs).
import type { MapOverview, ReachSp } from "../../api/types";

export interface OvMember {
  key: string;
  type: string;
  sf: number;
  bh: number | null;
}

// Corridor edges longer than this are dropped — a stylized transmission run
// shouldn't leap across the whole state between two weakly-related nodes.
const MAX_CORRIDOR_KM = 150;

function haversineKm(aLat: number, aLon: number, bLat: number, bLon: number): number {
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

// Prim's MST over haversine distance — the skeleton the corridor draws. Returns
// (i, j) index pairs into `nodes`.
function mstEdges(nodes: { lat: number; lon: number }[]): [number, number][] {
  const n = nodes.length;
  if (n < 2) return [];
  const inTree = new Array(n).fill(false);
  const best = new Array(n).fill(Infinity);
  const parent = new Array(n).fill(0);
  best[0] = 0;
  const edges: [number, number][] = [];
  for (let iter = 0; iter < n; iter++) {
    let u = -1;
    for (let v = 0; v < n; v++)
      if (!inTree[v] && (u === -1 || best[v] < best[u])) u = v;
    inTree[u] = true;
    if (u !== 0) edges.push([parent[u], u]);
    for (let v = 0; v < n; v++) {
      if (inTree[v]) continue;
      const d = haversineKm(nodes[u].lat, nodes[u].lon, nodes[v].lat, nodes[v].lon);
      if (d < best[v]) {
        best[v] = d;
        parent[v] = u;
      }
    }
  }
  return edges;
}

const located = (nodes: ReachSp[]) =>
  nodes.filter((n) => n.lat != null && n.lon != null) as (ReachSp & {
    lat: number;
    lon: number;
  })[];

type GeoPoint = { lon: number; lat: number };

export interface OverviewSources {
  gtcAxis: GeoJSON.FeatureCollection<GeoJSON.LineString>;
  gtcGate: GeoJSON.FeatureCollection<GeoJSON.LineString>;
  corridor: GeoJSON.FeatureCollection<GeoJSON.LineString>;
  radial: GeoJSON.FeatureCollection<GeoJSON.Point>;
}

// Split the overview into three typed sources. Every feature carries its
// `constraint_key` so the layers can be isolation-filtered to one constraint.
export function buildOverviewSources(overview: MapOverview | null): OverviewSources {
  const gtcAxis: GeoJSON.Feature<GeoJSON.LineString>[] = [];
  const gtcGate: GeoJSON.Feature<GeoJSON.LineString>[] = [];
  const corridor: GeoJSON.Feature<GeoJSON.LineString>[] = [];
  const radial: GeoJSON.Feature<GeoJSON.Point>[] = [];

  // A GTC is an interface limit, not an area. Its overview glyph derives a
  // signed |SF|-weighted axis, then marks that interface with a compact gate.
  const pole = (nodes: (ReachSp & { lat: number; lon: number })[], sign: 1 | -1) => {
    let wSum = 0;
    let lonSum = 0;
    let latSum = 0;
    for (const n of nodes) {
      if ((sign > 0 ? n.sf <= 0 : n.sf >= 0)) continue;
      const w = Math.abs(n.sf);
      wSum += w;
      lonSum += n.lon * w;
      latSum += n.lat * w;
    }
    return wSum > 0 ? { lon: lonSum / wSum, lat: latSum / wSum } : null;
  };

  // When the top-|SF| sample carries only one sign, it still deserves an
  // interface glyph. Find the weighted centroid and its principal spatial axis.
  // The axis spans the observed cluster, while a short minimum stub makes a
  // singleton legible without pretending that one point defines a wide corridor.
  const oneSidedAxis = (nodes: (ReachSp & { lat: number; lon: number })[]) => {
    let wSum = 0;
    let lonSum = 0;
    let latSum = 0;
    for (const n of nodes) {
      const w = Math.abs(n.sf);
      wSum += w;
      lonSum += n.lon * w;
      latSum += n.lat * w;
    }
    if (wSum <= 0) return null;
    const center: GeoPoint = { lon: lonSum / wSum, lat: latSum / wSum };
    const cosLat = Math.cos((center.lat * Math.PI) / 180);
    let xx = 0;
    let xy = 0;
    let yy = 0;
    for (const n of nodes) {
      const w = Math.abs(n.sf);
      const x = (n.lon - center.lon) * cosLat;
      const y = n.lat - center.lat;
      xx += w * x * x;
      xy += w * x * y;
      yy += w * y * y;
    }
    xx /= wSum;
    xy /= wSum;
    yy /= wSum;
    const angle = 0.5 * Math.atan2(2 * xy, xx - yy);
    const ux = Math.cos(angle);
    const uy = Math.sin(angle);
    const lambda = Math.max(0, (xx + yy + Math.hypot(xx - yy, 2 * xy)) / 2);
    // Degrees of latitude. Clamped so a singleton is a visible stub and a broad
    // footprint remains bounded at the overview zoom.
    const halfSpan = Math.max(0.07, Math.min(0.38, 1.5 * Math.sqrt(lambda)));
    return {
      a: { lon: center.lon - (ux * halfSpan) / cosLat, lat: center.lat - uy * halfSpan },
      b: { lon: center.lon + (ux * halfSpan) / cosLat, lat: center.lat + uy * halfSpan },
    };
  };

  // Emit each non-GTC constraint's MST run as a transmission corridor.
  const pushEdges = (
    nodes: (ReachSp & { lat: number; lon: number })[],
    ctype: string,
    constraint_key: string,
    maxKm: number
  ) => {
    for (const [i, j] of mstEdges(nodes)) {
      if (haversineKm(nodes[i].lat, nodes[i].lon, nodes[j].lat, nodes[j].lon) > maxKm)
        continue;
      corridor.push({
        type: "Feature",
        geometry: {
          type: "LineString",
          coordinates: [
            [nodes[i].lon, nodes[i].lat],
            [nodes[j].lon, nodes[j].lat],
          ],
        },
        properties: { constraint_key, ctype },
      });
    }
  };

  for (const c of overview?.constraints ?? []) {
    const nodes = located(c.nodes);
    if (!nodes.length) continue;
    const props = { constraint_key: c.constraint_key };

    if (c.ctype === "gtc") {
      const importPole = pole(nodes, -1);
      const exportPole = pole(nodes, 1);
      const axis =
        importPole && exportPole
          ? { a: importPole, b: exportPole }
          : oneSidedAxis(nodes);
      if (axis) {
        gtcAxis.push({
          type: "Feature",
          geometry: {
            type: "LineString",
            coordinates: [
              [axis.a.lon, axis.a.lat],
              [axis.b.lon, axis.b.lat],
            ],
          },
          properties: props,
        });
        // The GTC glyph is a small double crossbar perpendicular to the signed
        // axis: `— ║ —`. It reads as an interface gate/limit, not as a resource
        // node located at the midpoint.
        const midLat = (axis.a.lat + axis.b.lat) / 2;
        const midLon = (axis.a.lon + axis.b.lon) / 2;
        const cosLat = Math.cos((midLat * Math.PI) / 180);
        const dx = (axis.b.lon - axis.a.lon) * cosLat;
        const dy = axis.b.lat - axis.a.lat;
        const len = Math.hypot(dx, dy);
        if (len > 1e-6) {
          const along = 0.022;
          const halfBar = 0.095;
          const ux = dx / len;
          const uy = dy / len;
          for (const offset of [-along, along]) {
            const cx = midLon + (ux * offset) / cosLat;
            const cy = midLat + uy * offset;
            const px = (-uy * halfBar) / cosLat;
            const py = ux * halfBar;
            gtcGate.push({
              type: "Feature",
              geometry: {
                type: "LineString",
                coordinates: [
                  [cx - px, cy - py],
                  [cx + px, cy + py],
                ],
              },
              properties: props,
            });
          }
        }
      }
    } else if (c.ctype === "radial") {
      const p = nodes[0]; // peak-|SF| node (overview nodes are |SF|-sorted)
      radial.push({
        type: "Feature",
        geometry: { type: "Point", coordinates: [p.lon, p.lat] },
        properties: props,
      });
    } else {
      // transmission (and untyped): the MST run, minus cross-state leaps.
      pushEdges(nodes, "transmission", c.constraint_key, MAX_CORRIDOR_KM);
    }
  }

  const fc = <G extends GeoJSON.Geometry>(
    features: GeoJSON.Feature<G>[]
  ): GeoJSON.FeatureCollection<G> => ({ type: "FeatureCollection", features });

  return {
    gtcAxis: fc(gtcAxis),
    gtcGate: fc(gtcGate),
    corridor: fc(corridor),
    radial: fc(radial),
  };
}

// settlement_point → the constraints it belongs to (|SF|-desc), for the
// multi-constraint hover popover. Keyed by sp_id so the base `sps` hover can
// look it up directly.
export function buildSpMembers(overview: MapOverview | null): Map<string, OvMember[]> {
  const m = new Map<string, OvMember[]>();
  for (const c of overview?.constraints ?? []) {
    for (const n of c.nodes) {
      if (n.lat == null || n.lon == null) continue;
      const arr = m.get(n.settlement_point) ?? [];
      arr.push({ key: c.constraint_key, type: c.ctype ?? "", sf: n.sf, bh: c.binding_hours });
      m.set(n.settlement_point, arr);
    }
  }
  for (const arr of m.values()) arr.sort((a, b) => Math.abs(b.sf) - Math.abs(a.sf));
  return m;
}
