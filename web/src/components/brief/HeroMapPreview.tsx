import { useEffect, useMemo, useState } from "react";
import { fetchTopology, fetchErcotRange, fetchForecastRange } from "../../api/client";
import { computeLmpStats, normalizeLmpFromStats, lmpColor, type LmpStats } from "../../lib/colors";
import { loadTexasBorderRings } from "../../lib/texasOutline";
import { useTheme } from "../../lib/theme";

interface NodePoint {
  sp_id: string;
  lng: number;
  lat: number;
}

interface PreviewData {
  points: NodePoint[];
  values: Map<string, number>;
  stats: LmpStats;
  // Raw [lng, lat] rings from /texas.geojson (one array per ring, exterior and
  // any holes alike — an SVG path with fill-rule evenodd draws both correctly
  // without needing to tell them apart).
  borderRings: [number, number][][];
}

interface Props {
  // The delivery-day window + peak hour the Brief hero already carries (0002's
  // `cursor`) — the same coordinate the full Map link targets, so this frame
  // and that link agree on "when" without deriving it twice.
  cursor: { t: string; ws: string; we: string };
  // Which quantity actually has real dollars right now: settled DAM LMP once
  // it exists, the persisted-λ implied LMP before. Mirrors MapWorkspace's own
  // forecast/market split so the frame matches what the link opens into.
  basis: "forecast" | "settled";
}

const isPoint = (
  f: GeoJSON.Feature
): f is GeoJSON.Feature<GeoJSON.Point> => f.geometry?.type === "Point";

// Raw DAM SPP for the hour, keyed by settlement point.
async function loadSettledValues(t: Date, windowEnd: Date): Promise<Map<string, number>> {
  const values = new Map<string, number>();
  const range = await fetchErcotRange(t, windowEnd);
  const entry =
    range?.entries.find((e) => new Date(e.interval_ts).getTime() === t.getTime()) ??
    range?.entries[0];
  if (range && entry) {
    range.sp_ids.forEach((spId, i) => {
      const v = entry.spp[i];
      if (v != null) values.set(spId, v);
    });
  }
  return values;
}

// The model's deterministic forecast congestion + that hour's system-λ (the same implied-LMP
// convention the Map's forecast pane already renders — 0130's persisted-λ
// fallback included, since this is display, not a graded signal).
async function loadForecastValues(t: Date, windowEnd: Date): Promise<Map<string, number>> {
  const values = new Map<string, number>();
  const range = await fetchForecastRange(t, windowEnd);
  const entry =
    range?.entries.find((e) => new Date(e.interval_ts).getTime() === t.getTime()) ??
    range?.entries[0];
  if (entry?.system_lambda != null) {
    const lam = entry.system_lambda;
    for (const sp of entry.sps) {
      if (sp.forecast_congestion != null) values.set(sp.sp_id, sp.forecast_congestion + lam);
    }
  }
  return values;
}

// `basis` picks which source has real dollars right now, but the per-node
// nodal layer has its own gaps independent of that (e.g. the t+2 preview
// horizon publishes no per-SP forecast at all — only the mu/constraint layer
// that feeds the hero text — so the "correct" source can come back empty
// even on a day the hero itself resolved fine). Falling back to the other
// source rather than giving up keeps the frame honest without pretending
// the basis choice was wrong.
async function loadHourValues(
  t: Date,
  basis: "forecast" | "settled"
): Promise<Map<string, number>> {
  const windowEnd = new Date(t.getTime() + 60 * 60 * 1000);
  const [primary, fallback] =
    basis === "settled" ? [loadSettledValues, loadForecastValues] : [loadForecastValues, loadSettledValues];
  const values = await primary(t, windowEnd);
  return values.size ? values : fallback(t, windowEnd);
}

const VIEW_H = 300;
const PAD = 14;

// The Brief hero's inline map frame (0131): a cheap, non-interactive snapshot
// of the delivery day's peak hour, meant to sit as a big recognizable
// backdrop behind the headline rather than a small chart buried below the
// tables. It fetches independently of the hero text (already painted from
// the `hero` response) and fails silently to no frame at all — a reader who
// has never heard of a shadow price gets nothing worse than a plain
// headline, never a broken image.
//
// Pure visual, no link of its own: the caller (BriefPage) owns the frame's
// box, the text laid over it, and the click-through — this only fills
// whatever box it's given.
export default function HeroMapPreview({ cursor, basis }: Props) {
  const theme = useTheme();
  const [data, setData] = useState<PreviewData | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    setData(null);
    setFailed(false);
    const t = new Date(cursor.t);

    Promise.all([fetchTopology(), loadHourValues(t, basis), loadTexasBorderRings()])
      .then(([topology, values, borderRings]) => {
        if (!live) return;
        const points: NodePoint[] = (
          (topology as { settlement_points?: GeoJSON.FeatureCollection }).settlement_points
            ?.features ?? []
        )
          .filter(isPoint)
          .map((f) => ({
            sp_id: String(f.properties?.sp_id ?? ""),
            lng: f.geometry.coordinates[0],
            lat: f.geometry.coordinates[1],
          }))
          .filter((p) => p.sp_id);
        if (!points.length || !values.size || !borderRings.length) {
          setFailed(true);
          return;
        }
        setData({ points, values, stats: computeLmpStats(Array.from(values.values())), borderRings });
      })
      .catch(() => {
        if (live) setFailed(true);
      });
    return () => {
      live = false;
    };
  }, [cursor.t, basis]);

  // The state outline — not the node scatter's own bounding box — is the
  // projection's reference frame. ERCOT's footprint excludes El Paso and
  // slivers of the Panhandle and East Texas, so anchoring scale to the nodes
  // alone would crop the recognizable state shape and blow the dots up to
  // fill the frame edge to edge. Anchoring to the border instead gives a
  // real "what am I looking at" reference and, as a side effect, draws the
  // node cluster at a smaller, honest scale within it.
  //
  // One uniform scale (px per degree of latitude), also applied to longitude
  // after correcting for its foreshortening at this latitude — a real,
  // undistorted local projection. `xMaxYMid meet` then fits the whole shape
  // at full scale inside whatever box the caller gives this and pins it to
  // the right edge (vertically centered) rather than cropping or stretching,
  // so the outline stays fully visible and clear of the overlaid text on the
  // left.
  const projection = useMemo(() => {
    if (!data) return null;
    const { points, values, stats, borderRings } = data;
    const borderLngs = borderRings.flatMap((ring) => ring.map(([lng]) => lng));
    const borderLats = borderRings.flatMap((ring) => ring.map(([, lat]) => lat));
    const minLng = Math.min(...borderLngs);
    const maxLng = Math.max(...borderLngs);
    const minLat = Math.min(...borderLats);
    const maxLat = Math.max(...borderLats);
    const spanLat = Math.max(maxLat - minLat, 0.01);
    const lngCorrection = Math.cos(((minLat + maxLat) / 2) * (Math.PI / 180));
    const spanLngCorrected = Math.max((maxLng - minLng) * lngCorrection, 0.01);
    const usableH = VIEW_H - PAD * 2;
    const scale = usableH / spanLat;
    const usableW = spanLngCorrected * scale;
    const viewW = usableW + PAD * 2;
    const project = ([lng, lat]: [number, number]) => [
      PAD + (lng - minLng) * lngCorrection * scale,
      PAD + (1 - (lat - minLat) / spanLat) * usableH,
    ];
    const borderPath = borderRings
      .map((ring) => `M${ring.map((pt) => project(pt).map((v) => v.toFixed(1)).join(",")).join("L")}Z`)
      .join(" ");
    const dots = points.flatMap((p) => {
      const value = values.get(p.sp_id);
      if (value == null) return [];
      const [x, y] = project([p.lng, p.lat]);
      return [{ sp_id: p.sp_id, x, y, color: lmpColor(normalizeLmpFromStats(value, stats), theme) }];
    });
    return { viewW, borderPath, dots };
  }, [data, theme]);

  if (failed) return null;

  return (
    <div className="hero-map" aria-hidden="true">
      {!projection ? (
        <div className="hero-map__skeleton" />
      ) : (
        <svg
          viewBox={`0 0 ${projection.viewW} ${VIEW_H}`}
          preserveAspectRatio="xMaxYMid meet"
          className="hero-map__svg"
        >
          <path d={projection.borderPath} className="hero-map__border" fillRule="evenodd" />
          {projection.dots.map((d) => (
            <circle key={d.sp_id} cx={d.x} cy={d.y} r={1.3} fill={d.color} />
          ))}
        </svg>
      )}
      <style>{`
        .hero-map { position: absolute; inset: 0; overflow: hidden; }
        .hero-map__svg { display: block; width: 100%; height: 100%; }
        .hero-map__border { fill: var(--map-outline-fill); stroke: var(--map-outline); stroke-width: 1; }
        .hero-map__skeleton {
          width: 100%;
          height: 100%;
          background: linear-gradient(90deg, var(--bg-panel) 25%, var(--bg-surface) 50%, var(--bg-panel) 75%);
          background-size: 200% 100%;
          animation: hero-map-pulse 1.6s ease-in-out infinite;
        }
        @keyframes hero-map-pulse {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }
        @media (prefers-reduced-motion: reduce) {
          .hero-map__skeleton { animation: none; }
        }
      `}</style>
    </div>
  );
}
