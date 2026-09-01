import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  fetchErcotRange,
  fetchForecastRange,
  fetchTopology,
} from "../../api/client";
import type { ConstraintReach } from "../../api/types";
import {
  computeLmpStats,
  lmpColor,
  normalizeLmpFromStats,
  shiftFactorColor,
  type LmpStats,
} from "../../lib/colors";
import { useTheme } from "../../lib/theme";
import {
  fitBorderProjection,
  loadTexasBorderRings,
  settlementPointsFromTopology,
  type BorderRing,
  type SettlementPoint,
} from "../../lib/texasOutline";
import { REACH_K, useConstraintReach } from "../panels/ConstraintReach";

// The one lightweight, non-interactive Texas mini-map for every surface outside
// the full /map: the Brief hero backdrop (`lmp`), and the Brief/Matrix detail
// footprints (`constraint`, `node`). Mode picks the data and chrome; the border
// outline, projection, and SVG scaffolding are shared. This is NOT the
// interactive GridMap — it draws a static snapshot and hands off to /map.

interface NodePoint {
  lng: number;
  lat: number;
}

// Chrome common to the two footprint modes.
interface FootprintCommon {
  selectionKey: string;
  // Deep link to the full Map for this element (a control on the map itself).
  mapHref: string;
  // Intercept a plain left-click to navigate in-app (Matrix carries the shared
  // scrubber coordinate); modified/middle clicks fall through to the href.
  onNavigate?: (search: string) => void;
  // The "Grid footprint" heading — Brief keeps it, Matrix Read hides it.
  showTitle?: boolean;
  // Cursor instant whose CT delivery day the reach is served for.
  t?: Date;
}

type MiniMapProps =
  | {
      // Decorative hero backdrop: every node coloured by the hour's LMP.
      mode: "lmp";
      cursor: { t: string; ws: string; we: string };
      // Which quantity has real dollars now: settled DAM LMP, else implied-λ.
      basis: "forecast" | "settled";
    }
  | (FootprintCommon & {
      // A constraint's SF-reach members, coloured by import/export pole.
      mode: "constraint";
      // Matrix passes its already-fetched reach; Brief omits it and this fetches.
      reach?: ConstraintReach | null;
      reachLoading?: boolean;
    })
  | (FootprintCommon & {
      // A single settlement point.
      mode: "node";
      // Matrix passes the coordinate it has; Brief looks it up from topology.
      nodeLocation?: NodePoint | null;
    });

// Footprint frame; the hero derives its width from the outline.
const FP_W = 320;
const FP_H = 200;
const HERO_H = 300;
const HERO_PAD = 14;

// Raw DAM SPP for the hour, keyed by settlement point.
async function loadSettledValues(
  t: Date,
  windowEnd: Date
): Promise<Map<string, number>> {
  const values = new Map<string, number>();
  const range = await fetchErcotRange(t, windowEnd);
  const entry =
    range?.entries.find(
      (e) => new Date(e.interval_ts).getTime() === t.getTime()
    ) ?? range?.entries[0];
  if (range && entry) {
    range.sp_ids.forEach((spId, i) => {
      const v = entry.spp[i];
      if (v != null) values.set(spId, v);
    });
  }
  return values;
}

// Deterministic forecast congestion + that hour's system-λ (the implied-LMP
// convention the Map's forecast pane renders; display, not a graded signal).
async function loadForecastValues(
  t: Date,
  windowEnd: Date
): Promise<Map<string, number>> {
  const values = new Map<string, number>();
  const range = await fetchForecastRange(t, windowEnd);
  const entry =
    range?.entries.find(
      (e) => new Date(e.interval_ts).getTime() === t.getTime()
    ) ?? range?.entries[0];
  if (entry?.system_lambda != null) {
    const lam = entry.system_lambda;
    for (const sp of entry.sps) {
      if (sp.forecast_congestion != null)
        values.set(sp.sp_id, sp.forecast_congestion + lam);
    }
  }
  return values;
}

// `basis` picks the source with real dollars, but the per-node layer has its own
// gaps (e.g. the t+2 preview publishes no per-SP forecast), so fall back to the
// other source rather than showing an empty frame on a day that resolved fine.
async function loadHourValues(
  t: Date,
  basis: "forecast" | "settled"
): Promise<Map<string, number>> {
  const windowEnd = new Date(t.getTime() + 60 * 60 * 1000);
  const [primary, fallback] =
    basis === "settled"
      ? [loadSettledValues, loadForecastValues]
      : [loadForecastValues, loadSettledValues];
  const values = await primary(t, windowEnd);
  return values.size ? values : fallback(t, windowEnd);
}

export default function MiniMap(props: MiniMapProps) {
  const theme = useTheme();
  const isHero = props.mode === "lmp";

  const [border, setBorder] = useState<BorderRing[] | null>(null);
  useEffect(() => {
    let live = true;
    loadTexasBorderRings()
      .then((r) => live && setBorder(r))
      .catch(() => live && setBorder([]));
    return () => {
      live = false;
    };
  }, []);

  // --- lmp mode: the hour's node scatter -----------------------------------
  const lmp = props.mode === "lmp" ? props : null;
  const [lmpData, setLmpData] = useState<{
    points: SettlementPoint[];
    values: Map<string, number>;
    stats: LmpStats;
  } | null>(null);
  const [lmpFailed, setLmpFailed] = useState(false);
  useEffect(() => {
    if (!lmp) return;
    let live = true;
    setLmpData(null);
    setLmpFailed(false);
    const t = new Date(lmp.cursor.t);
    Promise.all([fetchTopology(), loadHourValues(t, lmp.basis)])
      .then(([topology, values]) => {
        if (!live) return;
        const points = settlementPointsFromTopology(topology);
        if (!points.length || !values.size) {
          setLmpFailed(true);
          return;
        }
        setLmpData({
          points,
          values,
          stats: computeLmpStats(Array.from(values.values())),
        });
      })
      .catch(() => live && setLmpFailed(true));
    return () => {
      live = false;
    };
  }, [lmp?.cursor.t, lmp?.basis]);

  // --- constraint mode: the SF reach ---------------------------------------
  const constraint = props.mode === "constraint" ? props : null;
  const providedReach = constraint?.reach;
  const hasProvidedReach = constraint != null && providedReach !== undefined;
  const { reach: fetchedReach, loading: fetchedReachLoading } =
    useConstraintReach(
      constraint && !hasProvidedReach ? constraint.selectionKey : null,
      REACH_K,
      constraint?.t
    );
  const reach = hasProvidedReach ? providedReach! : fetchedReach;
  const reachLoading = hasProvidedReach
    ? !!constraint?.reachLoading
    : fetchedReachLoading;

  // --- node mode: one located point ----------------------------------------
  const node = props.mode === "node" ? props : null;
  const [nodePoint, setNodePoint] = useState<NodePoint | null>(null);
  const [nodeResolved, setNodeResolved] = useState(props.mode !== "node");
  useEffect(() => {
    if (!node) {
      setNodePoint(null);
      setNodeResolved(true);
      return;
    }
    if (node.nodeLocation) {
      setNodePoint(node.nodeLocation);
      setNodeResolved(true);
      return;
    }
    let live = true;
    setNodeResolved(false);
    setNodePoint(null);
    fetchTopology()
      .then((topology) => {
        if (!live) return;
        const match = settlementPointsFromTopology(topology).find(
          (p) => p.sp_id === node.selectionKey
        );
        if (match) setNodePoint({ lng: match.lng, lat: match.lat });
      })
      .catch(() => {})
      .finally(() => live && setNodeResolved(true));
    return () => {
      live = false;
    };
  }, [node?.selectionKey, node?.nodeLocation]);

  // The state outline is the projection frame, not the node scatter's bbox:
  // ERCOT excludes El Paso and grid slivers, so anchoring to the nodes would
  // crop the recognizable shape and blow the dots up. The hero fills the height
  // (elastic width, right-pinned); the footprint fits inside its fixed box.
  const projection = useMemo(() => {
    if (!border) return null;
    return isHero
      ? fitBorderProjection(border, {
          height: HERO_H,
          pad: HERO_PAD,
          fit: "fillHeight",
        })
      : fitBorderProjection(border, { width: FP_W, height: FP_H });
  }, [border, isHero]);

  // The placed marks for the active mode.
  const dots = useMemo(() => {
    if (!projection) return [];
    if (props.mode === "lmp") {
      if (!lmpData) return [];
      const { points, values, stats } = lmpData;
      return points.flatMap((p) => {
        const v = values.get(p.sp_id);
        if (v == null) return [];
        const [x, y] = projection.project([p.lng, p.lat]);
        return [
          {
            id: p.sp_id,
            x,
            y,
            r: 1.3,
            color: lmpColor(normalizeLmpFromStats(v, stats), theme),
            focus: false,
          },
        ];
      });
    }
    if (props.mode === "constraint") {
      return (reach?.sps ?? []).flatMap((s) => {
        if (s.lat == null || s.lon == null) return [];
        const [x, y] = projection.project([s.lon, s.lat]);
        return [
          {
            id: s.settlement_point,
            x,
            y,
            r: 1.6,
            color: shiftFactorColor(s.sf),
            focus: false,
          },
        ];
      });
    }
    if (nodePoint) {
      const [x, y] = projection.project([nodePoint.lng, nodePoint.lat]);
      return [
        { id: props.selectionKey, x, y, r: 2.6, color: "var(--accent)", focus: true },
      ];
    }
    return [];
  }, [projection, props, lmpData, theme, reach, nodePoint]);

  // Hero: a decorative backdrop the caller lays text over; no chrome, no link,
  // fails silently to nothing.
  if (isHero) {
    if (lmpFailed) return null;
    return (
      <div className="mm-hero" aria-hidden="true">
        {!projection || !lmpData ? (
          <div className="mm-hero__skeleton" />
        ) : (
          <svg
            viewBox={`0 0 ${projection.width} ${projection.height}`}
            preserveAspectRatio="xMaxYMid meet"
            className="mm-hero__svg"
          >
            <path
              d={projection.borderPath}
              className="mm-border"
              fillRule="evenodd"
            />
            {dots.map((d) => (
              <circle key={d.id} cx={d.x} cy={d.y} r={d.r} fill={d.color} />
            ))}
          </svg>
        )}
        <MiniMapStyles />
      </div>
    );
  }

  // Footprint: an orientation map with a title, unavailable state, and the
  // handoff link to the full Map.
  const fp = props as FootprintCommon & { mode: "constraint" | "node" };
  const showTitle = fp.showTitle ?? true;
  const loading =
    !projection || (fp.mode === "constraint" ? reachLoading : !nodeResolved);
  const unavailable =
    !loading && dots.length === 0
      ? fp.mode === "constraint"
        ? "No located members to place on the grid."
        : "This settlement point isn’t geolocated."
      : null;
  const ariaLabel = unavailable
    ? `${fp.selectionKey} — location unavailable`
    : fp.mode === "constraint"
    ? `${fp.selectionKey} — ${dots.length} located member nodes`
    : `${fp.selectionKey} — located on the ERCOT grid`;

  return (
    <div className="mm-fp">
      {showTitle && <span className="bdp-section-title">Grid footprint</span>}
      <div className="mm-fp__frame">
        {loading ? (
          <div className="mm-fp__skeleton" />
        ) : (
          <svg
            viewBox={`0 0 ${FP_W} ${FP_H}`}
            preserveAspectRatio="xMidYMid meet"
            className="mm-fp__svg"
            role="img"
            aria-label={ariaLabel}
          >
            {projection && (
              <path
                d={projection.borderPath}
                className="mm-border"
                fillRule="evenodd"
              />
            )}
            {dots.map((d) => (
              <g key={d.id}>
                {d.focus && (
                  <circle cx={d.x} cy={d.y} r={5} className="mm-fp__focus-ring" />
                )}
                <circle cx={d.x} cy={d.y} r={d.r} fill={d.color} />
              </g>
            ))}
          </svg>
        )}
        {unavailable && <div className="mm-fp__unavailable">{unavailable}</div>}
        <Link
          className="mm-fp__map-btn"
          to={fp.mapHref}
          onClick={
            fp.onNavigate
              ? (event) => {
                  if (
                    event.defaultPrevented ||
                    event.button !== 0 ||
                    event.metaKey ||
                    event.ctrlKey ||
                    event.shiftKey ||
                    event.altKey
                  )
                    return;
                  event.preventDefault();
                  fp.onNavigate!(
                    new URL(fp.mapHref, window.location.origin).search
                  );
                }
              : undefined
          }
        >
          Open in Map →
        </Link>
      </div>
      <MiniMapStyles />
    </div>
  );
}

function MiniMapStyles() {
  return (
    <style>{`
      .mm-border { fill: var(--map-outline-fill); stroke: var(--map-outline); stroke-width: 1; }
      .mm-hero { position: absolute; inset: 0; overflow: hidden; }
      .mm-hero__svg { display: block; width: 100%; height: 100%; }
      .mm-hero__skeleton { width: 100%; height: 100%; background: linear-gradient(90deg, var(--bg-panel) 25%, var(--bg-surface) 50%, var(--bg-panel) 75%); background-size: 200% 100%; animation: mm-pulse 1.6s ease-in-out infinite; }
      .mm-fp { margin-top: 12px; margin-bottom: 22px; }
      .mm-fp__frame { position: relative; margin-top: 8px; border: 1px solid var(--border); background: var(--bg-base); }
      .mm-fp__svg { display: block; width: 100%; height: auto; }
      .mm-fp__focus-ring { fill: none; stroke: var(--accent); stroke-width: 1.2; opacity: 0.6; }
      .mm-fp__skeleton { width: 100%; aspect-ratio: ${FP_W} / ${FP_H}; background: linear-gradient(90deg, var(--bg-panel) 25%, var(--bg-surface) 50%, var(--bg-panel) 75%); background-size: 200% 100%; animation: mm-pulse 1.6s ease-in-out infinite; }
      .mm-fp__unavailable { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; padding: 12px; color: var(--text-muted); font-size: var(--fs-micro); text-align: center; }
      /* Open-in-Map sits as a control ON the map, bottom-right. */
      .mm-fp__map-btn { position: absolute; right: 8px; bottom: 8px; z-index: 1; display: inline-block; padding: 5px 10px; border: 1px solid color-mix(in srgb, var(--accent) 45%, var(--border)); border-radius: 3px; background: color-mix(in srgb, var(--bg-panel) 82%, transparent); color: var(--accent); font: 700 var(--fs-label) var(--font-label); letter-spacing: var(--track-label); text-decoration: none; backdrop-filter: blur(2px); box-shadow: 0 1px 6px rgb(0 0 0 / 18%); }
      .mm-fp__map-btn:hover { background: var(--accent-dim); border-color: var(--accent); }
      .mm-fp__map-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
      @keyframes mm-pulse { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
      @media (prefers-reduced-motion: reduce) { .mm-hero__skeleton, .mm-fp__skeleton { animation: none; } }
    `}</style>
  );
}
