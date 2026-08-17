// The ERCOT/Texas state-boundary reference used as a projection frame by the
// Brief's lightweight maps — the hero preview (HeroMapPreview) and the detail
// panel's footprint (BriefFootprintMap). Both draw the same outline from the
// same `/texas.geojson` the full interactive GridMap uses, so the loader lives
// once here rather than being re-implemented per map.

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
// correcting for its foreshortening at this latitude. `fit: "meet"` (default)
// scales to show the whole outline inside the box; the result is centered.
// Anchoring scale to the border — not the plotted points — keeps the state
// shape recognizable and the points at an honest size within it.
export interface FittedProjection {
  project: (coordinate: [number, number]) => [number, number];
  borderPath: string;
}

export function fitBorderProjection(
  rings: BorderRing[],
  width: number,
  height: number,
  pad = 10
): FittedProjection | null {
  if (!rings.length) return null;
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
  const usableW = width - pad * 2;
  const scale = Math.min(usableH / spanLat, usableW / spanLng);
  const drawnW = spanLng * scale;
  const drawnH = spanLat * scale;
  const offX = (width - drawnW) / 2;
  const offY = (height - drawnH) / 2;
  const project = ([lng, lat]: [number, number]): [number, number] => [
    offX + (lng - minLng) * lngCorrection * scale,
    offY + (1 - (lat - minLat) / spanLat) * drawnH,
  ];
  const borderPath = rings
    .map(
      (ring) =>
        `M${ring
          .map((pt) => project(pt).map((v) => v.toFixed(1)).join(","))
          .join("L")}Z`
    )
    .join(" ");
  return { project, borderPath };
}
