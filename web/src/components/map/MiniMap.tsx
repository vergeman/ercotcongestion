import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  fitBorderProjection,
  loadTexasBorderRings,
  type BorderRing,
} from "../../lib/texasOutline";
import {
  useMiniMapData,
  type FootprintCommon,
  type MiniMapProps,
} from "./useMiniMapData";

// The one lightweight, non-interactive Texas mini-map for every surface outside
// the full /map: the Brief hero backdrop (`lmp`), and the Brief/Matrix detail
// footprints (`constraint`, `node`). This file owns the outline projection and
// the SVG; `useMiniMapData` owns the fetching and colouring. NOT the interactive
// GridMap — it draws a static snapshot and hands off to /map.

export type { MiniMapProps };

// Footprint frame; the hero derives its width from the outline.
const FP_W = 320;
const FP_H = 200;
const HERO_H = 300;
const HERO_PAD = 14;

export default function MiniMap(props: MiniMapProps) {
  const isHero = props.mode === "lmp";
  const { dots: rawDots, loading: dataLoading, failed } = useMiniMapData(props);

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

  // Project each mark to screen space and size it by role.
  const dots = useMemo(() => {
    if (!projection) return [];
    return rawDots.map((d) => {
      const [x, y] = projection.project([d.lng, d.lat]);
      return {
        id: d.id,
        x,
        y,
        r: d.focus ? 2.6 : isHero ? 1.3 : 1.6,
        color: d.color,
        focus: d.focus,
      };
    });
  }, [projection, rawDots, isHero]);

  // Hero: a decorative backdrop the caller lays text over; no chrome, no link,
  // fails silently to nothing.
  if (isHero) {
    if (failed) return null;
    return (
      <div className="mm-hero" aria-hidden="true">
        {!projection || dataLoading ? (
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
  const loading = !projection || dataLoading;
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
