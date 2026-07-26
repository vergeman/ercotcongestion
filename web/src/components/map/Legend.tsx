import { useMemo } from "react";
import { cssVar, useTheme } from "../../lib/theme";
import type { SpRow } from "../../api/types";
import type { Palette } from "../../api/types";
import {
  normalizeLmpFromStats,
  normalizeCongestion,
  congestionColor,
  lmpColor,
  type LmpStats,
  type CongestionStats,
} from "../../lib/colors";

interface Props {
  palette: Palette;
  rows: SpRow[];
  // Cursor-day stats. Stable while playback stays within a delivery day.
  lmpStats: LmpStats | null;
  mcStats: CongestionStats | null;
  // Forecast-error view overrides: a custom palette title, and the diverging end
  // labels (default "export (−)" / "import (+)" for congestion; the error view
  // relabels these to "under-forecast" / "over-forecast"). Both apply only to the
  // congestion palette.
  titleOverride?: string;
  signLabels?: { neg: string; pos: string };
  // Overrides the palette bar's gradient — the forecast-error view passes its
  // emerald↔magenta ramp so the legend bar matches the map's error coloring.
  barGradientOverride?: string;
  // When set, appends a constraint-overlay key (violet marker, size ∝ max|SF|).
  // Shown only on the pane that carries the overlay, and only while it's on.
  // Legacy centroid overlay only — mutually exclusive with `overviewTypes`.
  constraintOverlay?: boolean;
  // When set, appends the de-piled overview's type key: three marks whose SHAPE
  // (region / corridor / point) carries the constraint type, so identity never
  // rides on hue alone (dataviz a11y). Replaces `constraintOverlay` when present.
  overviewTypes?: boolean;
}

// The overview's type marks. Hue is validated (CVD ΔE 47+ between the three;
// see plan/0092-0003) but the *shape* is the primary type channel — a colorblind
// or monochrome reader still tells region from corridor from point.
const OVERVIEW_TYPES: {
  label: string;
  mark: "region" | "corridor" | "point";
  token: string;
}[] = [
  // Theme-aware: resolved per theme via cssVar() so the type key stays legible
  // on a light ground (the --sf-* tokens carry a darkened light-mode set).
  { label: "GTC / interface — region", mark: "region", token: "--sf-gtc" },
  { label: "Transmission — corridor", mark: "corridor", token: "--sf-transmission" },
  { label: "Radial — point", mark: "point", token: "--sf-radial" },
];

function TypeMark({
  mark,
  color,
}: {
  mark: "region" | "corridor" | "point";
  color: string;
}) {
  return (
    <svg width="18" height="12" className="legend__type-svg" aria-hidden="true">
      {mark === "region" && (
        <rect x="1" y="2" width="16" height="8" rx="4" fill={color} opacity="0.85" />
      )}
      {mark === "corridor" && (
        <>
          <line x1="2" y1="6" x2="16" y2="6" stroke={color} strokeWidth="2" />
          <circle cx="2" cy="6" r="2" fill={color} />
          <circle cx="16" cy="6" r="2" fill={color} />
        </>
      )}
      {mark === "point" && (
        <circle cx="9" cy="6" r="4" fill="none" stroke={color} strokeWidth="2" />
      )}
    </svg>
  );
}

const HIST_BINS = 24;
// Widened from 130 so the palette title fits on one line and the diverging
// labels/sub uncramp. Inner elements size to the padded content box (width:100%)
// rather than this fixed value, so the gradient never overruns the container.
const BAR_W = 176;

function formatDollar(v: number): string {
  if (Math.abs(v) >= 1000) return `$${(v / 1000).toFixed(1)}k`;
  return `$${v.toFixed(0)}`;
}

export default function Legend({
  palette,
  rows,
  lmpStats,
  mcStats,
  titleOverride,
  signLabels,
  barGradientOverride,
  constraintOverlay = false,
  overviewTypes = false,
}: Props) {
  // Subscribes the legend to theme flips so the cssVar() type-mark lookups below
  // re-resolve (SVG presentation attributes cannot take var()).
  useTheme();
  const isCongestion = palette === "congestion";
  const isLmp = palette === "lmp";
  const isOff = palette === "off";

  // Snapshot distribution, binned in color-space so each bar sits directly above
  // the gradient color its values fall in. Computed for BOTH palettes (LMP off
  // spp, congestion off the signed value mapped through the same diverging
  // normalization the map uses) so every legend carries the distribution.
  const hist = useMemo(() => {
    if (rows.length === 0) return null;
    const counts = new Array(HIST_BINS).fill(0);
    let n = 0;
    if (isLmp && lmpStats) {
      for (const r of rows) {
        if (r.spp == null) continue;
        const norm = normalizeLmpFromStats(r.spp, lmpStats); // 0..1
        let idx = Math.floor(norm * HIST_BINS);
        if (idx >= HIST_BINS) idx = HIST_BINS - 1;
        if (idx < 0) idx = 0;
        counts[idx] += 1;
        n += 1;
      }
    } else if (isCongestion && mcStats) {
      for (const r of rows) {
        if (r.congestion == null) continue;
        const norm = normalizeCongestion(r.congestion, mcStats); // −1..1
        const t = (norm + 1) / 2; // 0..1, center = 0
        let idx = Math.floor(t * HIST_BINS);
        if (idx >= HIST_BINS) idx = HIST_BINS - 1;
        if (idx < 0) idx = 0;
        counts[idx] += 1;
        n += 1;
      }
    } else {
      return null;
    }
    if (n === 0) return null;
    const peak = Math.max(...counts);
    return { counts, peak };
  }, [rows, isLmp, isCongestion, lmpStats, mcStats]);

  // SPP tick marks: p_low (left), median (center), p_high (right).
  const lmpTicks = useMemo(() => {
    if (!isLmp || !lmpStats) return [];
    return [
      { label: formatDollar(lmpStats.p_low), pct: 0 },
      { label: formatDollar(lmpStats.median), pct: 50 },
      { label: formatDollar(lmpStats.p_high), pct: 100 },
    ];
  }, [isLmp, lmpStats]);

  // Built from the palette functions so the bar tracks the theme (light gets the
  // grey center + deepened ends); useTheme() above re-renders on a flip.
  const barGradient =
    barGradientOverride ??
    (isCongestion
      ? `linear-gradient(to right, ${congestionColor(
          -1
        )}, ${congestionColor(0)}, ${congestionColor(1)})`
      : `linear-gradient(to right, ${lmpColor(0)}, ${lmpColor(0.5)}, ${lmpColor(
          1
        )})`);

  // Title splits into a name (own line) and the quantity/equation (own line,
  // smaller). Built-ins carry both explicitly; an override is split on " · ".
  let titleName: string;
  let titleEq: string;
  if (titleOverride) {
    const dot = titleOverride.indexOf(" · ");
    titleName = dot >= 0 ? titleOverride.slice(0, dot) : titleOverride;
    titleEq = dot >= 0 ? titleOverride.slice(dot + 3) : "";
  } else if (isOff) {
    titleName = "Palette off";
    titleEq = "overlay only";
  } else if (isCongestion) {
    titleName = "Congestion";
    titleEq = "SPP − λ ($/MWh)";
  } else {
    titleName = "DAM SPP / LMP";
    titleEq = "($/MWh)";
  }
  const negLabel = signLabels?.neg ?? "Export";
  const posLabel = signLabels?.pos ?? "Import";

  return (
    <div className="legend">
      <div className="legend__title label">{titleName}</div>
      {titleEq && <div className="legend__eq label">{titleEq}</div>}

      {/* Snapshot distribution over the cursor-day bin range, on every legend. */}
      {!isOff && hist && (
        <div className="legend__hist">
          {hist.counts.map((c, i) => (
            <div
              key={i}
              className="legend__hist-bar"
              style={{ height: `${(c / hist.peak) * 100}%` }}
            />
          ))}
        </div>
      )}

      {!isOff && (
        <div className="legend__bar" style={{ background: barGradient }} />
      )}

      {/* Diverging congestion family: signed, center = 0, edges = ±p_high. */}
      {isCongestion && mcStats && (
        <>
          <div className="legend__ticks">
            <span className="label mono legend__tick legend__tick--start">
              −{formatDollar(mcStats.p_high)}
            </span>
            <span className="label mono legend__tick" style={{ left: "50%" }}>
              0
            </span>
            <span className="label mono legend__tick legend__tick--end">
              +{formatDollar(mcStats.p_high)}
            </span>
          </div>
          <div className="legend__labels">
            <span className="label">{negLabel}</span>
            <span className="label">{posLabel}</span>
          </div>
        </>
      )}

      {isCongestion && !mcStats && (
        <div className="legend__labels">
          <span className="label mono">—</span>
          <span className="label mono">—</span>
        </div>
      )}

      {isLmp && lmpStats && (
        <div className="legend__ticks">
          {lmpTicks.map((t, i) => (
            <span
              key={i}
              className={`label mono legend__tick${
                t.pct === 0
                  ? " legend__tick--start"
                  : t.pct === 100
                  ? " legend__tick--end"
                  : ""
              }`}
              style={t.pct === 0 || t.pct === 100 ? undefined : { left: `${t.pct}%` }}
            >
              {t.label}
            </span>
          ))}
        </div>
      )}

      {isLmp && !lmpStats && (
        <div className="legend__labels">
          <span className="label mono">—</span>
          <span className="label mono">—</span>
        </div>
      )}

      {overviewTypes && (
        <div className="legend__types">
          {OVERVIEW_TYPES.map((t) => (
            <div key={t.mark} className="legend__type-row">
              <TypeMark mark={t.mark} color={cssVar(t.token)} />
              <span className="label legend__type-text">{t.label}</span>
            </div>
          ))}
        </div>
      )}

      {constraintOverlay && !overviewTypes && (
        <div className="legend__overlay">
          <span className="legend__overlay-dot" />
          <span className="label legend__overlay-text">
            Constraints · size ∝ max |SF|
          </span>
        </div>
      )}

      <style>{`
        .legend {
          position: absolute;
          bottom: 88px;
          left: 12px;
          background: var(--bg-glass);
          border: 1px solid var(--border);
          border-radius: 4px;
          padding: 8px 10px;
          width: ${BAR_W + 20}px;
          backdrop-filter: blur(4px);
        }
        .legend__title {
          font-size: var(--fs-md);
          font-weight: 600;
          color: var(--text-primary);
          line-height: 1.25;
        }
        .legend__eq {
          margin-top: 3px;
          margin-bottom: 7px;
          font-size: var(--fs-label);
          color: var(--text-muted);
          line-height: 1.25;
        }
        .legend__hist {
          height: 26px;
          width: 100%;
          display: flex;
          align-items: flex-end;
          gap: 1px;
          margin-bottom: 2px;
        }
        .legend__hist-bar {
          flex: 1;
          background: var(--text-muted, #64748b);
          opacity: 0.55;
          min-height: 1px;
        }
        .legend__bar {
          height: 8px;
          width: 100%;
          border-radius: 4px;
          margin-bottom: 3px;
        }
        .legend__labels {
          display: flex;
          justify-content: space-between;
          width: 100%;
        }
        .legend__labels .label {
          font-size: var(--fs-body);
        }
        .legend__ticks {
          position: relative;
          width: 100%;
          height: 12px;
        }
        .legend__tick {
          position: absolute;
          top: 0;
          transform: translateX(-50%);
          font-size: var(--fs-label);
          opacity: 0.8;
          white-space: nowrap;
        }
        /* End ticks anchor to the bar edges (matching the Export/Import labels)
           so they don't bleed past the container the way a centered −50% does. */
        .legend__tick--start {
          left: 0;
          transform: none;
        }
        .legend__tick--end {
          left: auto;
          right: 0;
          transform: none;
        }
        .legend__types {
          margin-top: 9px;
          padding-top: 9px;
          border-top: 1px solid var(--border);
        }
        .legend__type-row {
          display: flex;
          align-items: center;
          gap: 6px;
          margin-bottom: 2px;
        }
        .legend__type-svg {
          flex-shrink: 0;
        }
        .legend__type-text {
          font-size: var(--fs-label);
          opacity: 0.85;
        }
        .legend__overlay {
          display: flex;
          align-items: center;
          gap: 6px;
          margin-top: 6px;
          padding-top: 5px;
          border-top: 1px solid var(--border);
        }
        .legend__overlay-dot {
          width: 9px;
          height: 9px;
          border-radius: 50%;
          background: rgba(167, 139, 250, 0.55);
          border: 1px solid #c4b5fd;
          flex-shrink: 0;
        }
        .legend__overlay-text {
          font-size: var(--fs-label);
          opacity: 0.8;
        }
      `}</style>
    </div>
  );
}
