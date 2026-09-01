// The ERCOT/Texas state-boundary reference used as a projection frame by the
// lightweight MiniMap (hero backdrop, Brief/Matrix footprints). They draw the
// same outline from the same `/texas.geojson` the full interactive GridMap
// uses, so the loader and projection live once here rather than per map.

// One ring of [lng, lat] pairs (exterior or a hole — an SVG path with fill-rule
// evenodd draws both correctly without needing to tell them apart).
export type BorderRing = [number, number][];

// Every polygon ring in `/texas.geojson`, flattened. Fails soft to an empty
// array: a map that can't load the outline paints nothing rather than throwing.
export async function loadTexasBorderRings(): Promise<BorderRing[]> {
  const response = await fetch("/texas.geojson");
  if (!response.ok) return [];
  const geojson = (await response.json()) as GeoJSON.FeatureCollection;
  const rings: BorderRing[] = [];
  for (const feature of geojson.features) {
    const geometry = feature.geometry;
    const polygons =
      geometry.type === "Polygon"
        ? [geometry.coordinates]
        : geometry.type === "MultiPolygon"
        ? geometry.coordinates
        : [];
    for (const polygon of polygons) {
      for (const ring of polygon) {
        rings.push(ring.map(([lng, lat]) => [lng, lat]));
      }
    }
  }
  return rings;
}

// A local, undistorted projection fitted to the border's bounding box: one
// uniform scale (px per degree of latitude) applied to longitude too after
// correcting for its foreshortening at this latitude. Anchoring scale to the
// border — not the plotted points — keeps the state shape recognizable and the
// points at an honest size within it. `width`/`height` are the returned viewBox.
//
// fit:
//   "meet"       (default) — scale to show the whole outline inside width×height,
//                 centered. Needs both dims.
//   "fillHeight" — scale to the height only; width is derived from the outline's
//                 span (the caller right-pins via preserveAspectRatio). Used by
//                 the hero backdrop, where width is elastic.
export interface FittedProjection {
  project: (coordinate: [number, number]) => [number, number];
  borderPath: string;
  width: number;
  height: number;
}

export function fitBorderProjection(
  rings: BorderRing[],
  opts: {
    height: number;
    width?: number;
    pad?: number;
    fit?: "meet" | "fillHeight";
  }
): FittedProjection | null {
  if (!rings.length) return null;
  const { height, pad = 10, fit = "meet" } = opts;
  const lngs = rings.flatMap((ring) => ring.map(([lng]) => lng));
  const lats = rings.flatMap((ring) => ring.map(([, lat]) => lat));
  const minLng = Math.min(...lngs);
  const maxLng = Math.max(...lngs);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const spanLat = Math.max(maxLat - minLat, 0.01);
  const lngCorrection = Math.cos(((minLat + maxLat) / 2) * (Math.PI / 180));
  const spanLng = Math.max((maxLng - minLng) * lngCorrection, 0.01);
  const usableH = height - pad * 2;

  let width: number;
  let scale: number;
  let offX: number;
  let offY: number;
  if (fit === "fillHeight") {
    scale = usableH / spanLat;
    width = spanLng * scale + pad * 2;
    offX = pad;
    offY = pad;
  } else {
    width = opts.width ?? height;
    scale = Math.min(usableH / spanLat, (width - pad * 2) / spanLng);
    offX = (width - spanLng * scale) / 2;
    offY = (height - spanLat * scale) / 2;
  }
  const project = ([lng, lat]: [number, number]): [number, number] => [
    offX + (lng - minLng) * lngCorrection * scale,
    offY + (1 - (lat - minLat) / spanLat) * spanLat * scale,
  ];
  const borderPath = rings
    .map(
      (ring) =>
        `M${ring
          .map((pt) => project(pt).map((v) => v.toFixed(1)).join(","))
          .join("L")}Z`
    )
    .join(" ");
  return { project, borderPath, width, height };
}

// The settlement-point features of a /topology response as plain coordinates.
// Both MiniMap modes that place nodes (the LMP scatter and a single located
// node) read this, so the GeoJSON dig lives once.
export interface SettlementPoint {
  sp_id: string;
  lng: number;
  lat: number;
}

export function settlementPointsFromTopology(
  topology: unknown
): SettlementPoint[] {
  const features =
    (topology as { settlement_points?: GeoJSON.FeatureCollection })
      .settlement_points?.features ?? [];
  return features
    .filter(
      (f): f is GeoJSON.Feature<GeoJSON.Point> => f.geometry?.type === "Point"
    )
    .map((f) => ({
      sp_id: String(f.properties?.sp_id ?? ""),
      lng: f.geometry.coordinates[0],
      lat: f.geometry.coordinates[1],
    }))
    .filter((p) => p.sp_id);
}
