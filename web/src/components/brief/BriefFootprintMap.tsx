import { useEffect, useMemo, useState } from "react";
import { fetchTopology } from "../../api/client";
import { shiftFactorColor } from "../../lib/colors";
import {
  fitBorderProjection,
  loadTexasBorderRings,
  type BorderRing,
} from "../../lib/texasOutline";
import {
  selectionGeo,
  selectionKey,
  type BriefSelection,
} from "../../lib/briefSelection";
import { useConstraintReach } from "../panels/ConstraintReach";

// The detail panel's abstract footprint (plan/0135): a small, non-interactive
// orientation map, NOT a second Map workspace. It answers "where on the grid is
// this?" and nothing more — a constraint paints its located SF-reach members
// (coloured by import/export pole), a node paints its single located point.
//
// It fetches independently of the full Map's frame and fails to an honest
// unavailable-location state rather than inventing a position: a hub or an
// aggregate settlement point with no coordinate says so, it does not drop a dot
// at the origin. A constraint reuses the shared reach hook/cache, so opening the
// panel costs at most one /map/reach call shared with the evidence list.

const VIEW_W = 320;
const VIEW_H = 200;

interface NodePoint {
  lng: number;
  lat: number;
}

const isPoint = (
  f: GeoJSON.Feature
): f is GeoJSON.Feature<GeoJSON.Point> => f.geometry?.type === "Point";

export default function BriefFootprintMap({
  selection,
}: {
  selection: BriefSelection;
}) {
  const geo = selectionGeo(selection);
  const key = selectionKey(selection);

  // A constraint's members come from the shared reach (already warm if the
  // evidence list fetched it); a node is located from the topology instead.
  const { reach, loading: reachLoading } = useConstraintReach(
    geo === "constraint" ? key : null
  );
  const [border, setBorder] = useState<BorderRing[] | null>(null);
  const [nodePoint, setNodePoint] = useState<NodePoint | null>(null);
  const [nodeResolved, setNodeResolved] = useState(geo !== "node");

  useEffect(() => {
    let live = true;
    loadTexasBorderRings()
      .then((rings) => live && setBorder(rings))
      .catch(() => live && setBorder([]));
    return () => {
      live = false;
    };
  }, []);

  // Locate the selected node from the topology's settlement-point features.
  useEffect(() => {
    if (geo !== "node") {
      setNodePoint(null);
      setNodeResolved(true);
      return;
    }
    let live = true;
    setNodeResolved(false);
    setNodePoint(null);
    fetchTopology()
      .then((topology) => {
        if (!live) return;
        const features =
          (topology as { settlement_points?: GeoJSON.FeatureCollection })
            .settlement_points?.features ?? [];
        const match = features
          .filter(isPoint)
          .find((f) => String(f.properties?.sp_id ?? "") === key);
        if (match) {
          const [lng, lat] = match.geometry.coordinates;
          setNodePoint({ lng, lat });
        }
      })
      .catch(() => {})
      .finally(() => {
        if (live) setNodeResolved(true);
      });
    return () => {
      live = false;
    };
  }, [geo, key]);

  const projection = useMemo(
    () => (border ? fitBorderProjection(border, VIEW_W, VIEW_H) : null),
    [border]
  );

  // The placed marks. A constraint keeps only members with real coordinates; a
  // node is its single located point.
  const dots = useMemo(() => {
    if (!projection) return [];
    if (geo === "constraint") {
      return (reach?.sps ?? []).flatMap((s) => {
        if (s.lat == null || s.lon == null) return [];
        const [x, y] = projection.project([s.lon, s.lat]);
        return [
          {
            id: s.settlement_point,
            x,
            y,
            color: shiftFactorColor(s.sf),
            focus: false,
          },
        ];
      });
    }
    if (nodePoint) {
      const [x, y] = projection.project([nodePoint.lng, nodePoint.lat]);
      return [{ id: key, x, y, color: "var(--accent)", focus: true }];
    }
    return [];
  }, [projection, geo, reach, nodePoint, key]);

  const loading =
    !projection || (geo === "constraint" ? reachLoading : !nodeResolved);
  const unavailable =
    !loading &&
    dots.length === 0 &&
    (geo === "constraint"
      ? "No located members to place on the grid."
      : "This settlement point isn’t geolocated.");

  return (
    <div className="bfm">
      <span className="bdp-fact__label">Grid footprint</span>
      <div className="bfm__frame">
        {loading ? (
          <div className="bfm__skeleton" />
        ) : (
          <svg
            viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
            preserveAspectRatio="xMidYMid meet"
            className="bfm__svg"
            role="img"
            aria-label={
              unavailable
                ? `${key} — location unavailable`
                : geo === "constraint"
                ? `${key} — ${dots.length} located member nodes`
                : `${key} — located on the ERCOT grid`
            }
          >
            {projection && (
              <path
                d={projection.borderPath}
                className="bfm__border"
                fillRule="evenodd"
              />
            )}
            {dots.map((d) => (
              <g key={d.id}>
                {d.focus && (
                  <circle
                    cx={d.x}
                    cy={d.y}
                    r={5}
                    className="bfm__focus-ring"
                  />
                )}
                <circle
                  cx={d.x}
                  cy={d.y}
                  r={d.focus ? 2.6 : 1.6}
                  fill={d.color}
                />
              </g>
            ))}
          </svg>
        )}
        {unavailable && <div className="bfm__unavailable">{unavailable}</div>}
      </div>

      <style>{`
        .bfm { margin-top: 16px; }
        .bfm__frame { position: relative; margin-top: 8px; border: 1px solid var(--border); background: var(--bg-base); }
        .bfm__svg { display: block; width: 100%; height: auto; }
        .bfm__border { fill: var(--map-outline-fill); stroke: var(--map-outline); stroke-width: 1; }
        .bfm__focus-ring { fill: none; stroke: var(--accent); stroke-width: 1.2; opacity: 0.6; }
        .bfm__skeleton { width: 100%; aspect-ratio: ${VIEW_W} / ${VIEW_H}; background: linear-gradient(90deg, var(--bg-panel) 25%, var(--bg-surface) 50%, var(--bg-panel) 75%); background-size: 200% 100%; animation: bfm-pulse 1.6s ease-in-out infinite; }
        .bfm__unavailable { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; padding: 12px; color: var(--text-muted); font-size: var(--fs-micro); text-align: center; }
        @keyframes bfm-pulse { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
        @media (prefers-reduced-motion: reduce) { .bfm__skeleton { animation: none; } }
      `}</style>
    </div>
  );
}
