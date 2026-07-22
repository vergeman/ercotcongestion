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

export interface OverviewSources {
  gtc: GeoJSON.FeatureCollection<GeoJSON.Point>;
  corridor: GeoJSON.FeatureCollection<GeoJSON.LineString>;
  radial: GeoJSON.FeatureCollection<GeoJSON.Point>;
}

// Split the overview into three typed sources. Every feature carries its
// `constraint_key` so the layers can be isolation-filtered to one constraint.
export function buildOverviewSources(overview: MapOverview | null): OverviewSources {
  const gtc: GeoJSON.Feature<GeoJSON.Point>[] = [];
  const corridor: GeoJSON.Feature<GeoJSON.LineString>[] = [];
  const radial: GeoJSON.Feature<GeoJSON.Point>[] = [];

  // Emit each constraint's MST run as corridor lines, tagged with its type so the
  // line layer can color GTC skeletons and transmission corridors differently.
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
      // Region = blended circle cloud over its nodes, plus its MST skeleton so the
      // nodes read as one connected constraint (like the old metaball + skeleton).
      for (const n of nodes)
        gtc.push({
          type: "Feature",
          geometry: { type: "Point", coordinates: [n.lon, n.lat] },
          properties: props,
        });
      // GTC skeletons are NOT distance-clipped — an interface constraint is
      // genuinely region-wide, so its MST connects even far-apart lobes.
      pushEdges(nodes, "gtc", c.constraint_key, Infinity);
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

  return { gtc: fc(gtc), corridor: fc(corridor), radial: fc(radial) };
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
