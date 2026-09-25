// Build GeoJSON sources for the constraint overview.
import type { MapOverview, ReachSp } from "../../api/types";

export interface OvMember {
  key: string;
  type: string;
  sf: number;
  bh: number | null;
}

// Avoid drawing corridor links across the state.
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

// Return minimum-spanning-tree edges for a corridor.
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
  gtcHit: GeoJSON.FeatureCollection<GeoJSON.Point>;
  corridor: GeoJSON.FeatureCollection<GeoJSON.LineString>;
  radial: GeoJSON.FeatureCollection<GeoJSON.Point>;
}

// Build sources by constraint type. Each feature keeps its constraint key.
export function buildOverviewSources(overview: MapOverview | null): OverviewSources {
  const gtcAxis: GeoJSON.Feature<GeoJSON.LineString>[] = [];
  const gtcGate: GeoJSON.Feature<GeoJSON.LineString>[] = [];
  const gtcHit: GeoJSON.Feature<GeoJSON.Point>[] = [];
  const corridor: GeoJSON.Feature<GeoJSON.LineString>[] = [];
  const radial: GeoJSON.Feature<GeoJSON.Point>[] = [];

  // Locate each end of a GTC from its signed, weighted nodes.
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

  // Use the cluster's main direction when only one end is available.
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
    // Adjust longitude for latitude before finding the direction.
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
    // Keep the marker visible without letting it span the map.
    const halfSpan = Math.max(0.07, Math.min(0.38, 1.5 * Math.sqrt(lambda)));
    return {
      a: { lon: center.lon - (ux * halfSpan) / cosLat, lat: center.lat - uy * halfSpan },
      b: { lon: center.lon + (ux * halfSpan) / cosLat, lat: center.lat + uy * halfSpan },
    };
  };

  // Draw non-GTC constraints as connected corridors.
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
      const negativePole = pole(nodes, -1);
      const positivePole = pole(nodes, 1);
      const axis =
        negativePole && positivePole
          ? { a: negativePole, b: positivePole }
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
        const midLat = (axis.a.lat + axis.b.lat) / 2;
        const midLon = (axis.a.lon + axis.b.lon) / 2;
        // A larger invisible target makes the gate easier to hover.
        gtcHit.push({
          type: "Feature",
          geometry: { type: "Point", coordinates: [midLon, midLat] },
          properties: props,
        });
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
      const p = nodes[0];
      radial.push({
        type: "Feature",
        geometry: { type: "Point", coordinates: [p.lon, p.lat] },
        properties: props,
      });
    } else {
      pushEdges(nodes, "transmission", c.constraint_key, MAX_CORRIDOR_KM);
    }
  }

  const fc = <G extends GeoJSON.Geometry>(
    features: GeoJSON.Feature<G>[]
  ): GeoJSON.FeatureCollection<G> => ({ type: "FeatureCollection", features });

  return {
    gtcAxis: fc(gtcAxis),
    gtcGate: fc(gtcGate),
    gtcHit: fc(gtcHit),
    corridor: fc(corridor),
    radial: fc(radial),
  };
}

// Index nearby constraint marks by settlement point for the hover popover.
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
