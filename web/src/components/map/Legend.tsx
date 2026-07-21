import { useMemo } from "react";
import { cssVar, useTheme } from "../../lib/theme";
import type { SpRow } from "../../api/types";
import type { Palette } from "../../api/types";
import {
  LMP_PCT_LOW,
  LMP_PCT_HIGH,
  normalizeLmpFromStats,
  type LmpStats,
  type ModeledCongestionStats,
} from "../../lib/colors";

interface Props {
  palette: Palette;
  rows: SpRow[];
  // Window-wide stats. Stable across playback.
  lmpStats: LmpStats | null;
  mcStats: ModeledCongestionStats | null;
  // "full" (default): palette + histogram/ticks. "palette-only": palette +
  // ticks/labels/sub only — used on the placeholder (prediction) pane.
  variant?: "full" | "palette-only";
  // Optional caption under the palette; distinguishes the two panes.
  paneLabel?: string;
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
const BAR_W = 130;

function formatDollar(v: number): string {
  if (Math.abs(v) >= 1000) return `$${(v / 1000).toFixed(1)}k`;
  return `$${v.toFixed(0)}`;
}

export default function Legend({
  palette,
  rows,
  lmpStats,
  mcStats,
  variant = "full",
  paneLabel,
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
  const isPaletteOnly = variant === "palette-only";

  // SPP histogram for the *current snapshot*, binned in color-space so each
  // bar aligns directly above the gradient color it falls in.
  const lmpHist = useMemo(() => {
    if (!isLmp || rows.length === 0 || !lmpStats) return null;
    const counts = new Array(HIST_BINS).fill(0);
    for (const r of rows) {
      if (r.spp == null) continue;
      const norm = normalizeLmpFromStats(r.spp, lmpStats); // 0..1
      let idx = Math.floor(norm * HIST_BINS);
      if (idx >= HIST_BINS) idx = HIST_BINS - 1;
      if (idx < 0) idx = 0;
      counts[idx] += 1;
    }
    const peak = Math.max(...counts);
    return { counts, peak };
  }, [rows, isLmp, lmpStats]);

  // SPP tick marks: p_low (left), median (center), p_high (right).
  const lmpTicks = useMemo(() => {
    if (!isLmp || !lmpStats) return [];
    return [
      { label: formatDollar(lmpStats.p_low), pct: 0 },
      { label: formatDollar(lmpStats.median), pct: 50 },
      { label: formatDollar(lmpStats.p_high), pct: 100 },
    ];
  }, [isLmp, lmpStats]);

  // Current-snapshot SPP min/mean/max, distinct from the window-wide
  // percentile range above.
  const lmpSnapshot = useMemo(() => {
    if (!isLmp) return null;
    let min = Infinity;
    let max = -Infinity;
    let sum = 0;
    let n = 0;
    for (const r of rows) {
      if (r.spp == null) continue;
      if (r.spp < min) min = r.spp;
      if (r.spp > max) max = r.spp;
      sum += r.spp;
      n += 1;
    }
    if (n === 0) return null;
    return { min, mean: sum / n, max };
  }, [rows, isLmp]);

  const barGradient =
    barGradientOverride ??
    (isCongestion
      ? "linear-gradient(to right, rgb(59,130,246), rgb(232,226,215), rgb(239,68,68))"
      : "linear-gradient(to right, #3b82f6, #e2e8d0, #f97316)");

  const title =
    titleOverride ??
    (isOff
      ? "Palette off · overlay only"
      : isCongestion
      ? "Congestion · SPP − λ ($/MWh)"
      : "DAM SPP / LMP ($/MWh)");
  const negLabel = signLabels?.neg ?? "export (−)";
  const posLabel = signLabels?.pos ?? "import (+)";

  return (
    <div className="legend">
      <div className="legend__title label">{title}</div>

      {/* LMP: snapshot histogram against window-wide bin range */}
      {isLmp && lmpHist && !isPaletteOnly && (
        <div className="legend__hist">
          {lmpHist.counts.map((c, i) => (
            <div
              key={i}
              className="legend__hist-bar"
              style={{ height: `${(c / lmpHist.peak) * 100}%` }}
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
            <span className="label mono legend__tick" style={{ left: "0%" }}>
              −{formatDollar(mcStats.p_high)}
            </span>
            <span className="label mono legend__tick" style={{ left: "50%" }}>
              0
            </span>
            <span className="label mono legend__tick" style={{ left: "100%" }}>
              +{formatDollar(mcStats.p_high)}
            </span>
          </div>
          <div className="legend__labels">
            <span className="label">{negLabel}</span>
            <span className="label">{posLabel}</span>
          </div>
          <div className="legend__sub label">
            window |max| {formatDollar(mcStats.max_abs)} · anchor = |value| P90
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
        <>
          <div className="legend__ticks">
            {lmpTicks.map((t, i) => (
              <span
                key={i}
                className="label mono legend__tick"
                style={{ left: `${t.pct}%` }}
              >
                {t.label}
              </span>
            ))}
          </div>
          <div className="legend__sub label">
            window {formatDollar(lmpStats.min)} – {formatDollar(lmpStats.max)} ·{" "}
            P{Math.round(LMP_PCT_LOW * 100)}–P{Math.round(LMP_PCT_HIGH * 100)}
          </div>
          {lmpSnapshot && (
            <div className="legend__sub label">
              snapshot {formatDollar(lmpSnapshot.min)} –{" "}
              {formatDollar(lmpSnapshot.max)} · avg{" "}
              {formatDollar(lmpSnapshot.mean)}
            </div>
          )}
        </>
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
          <div className="legend__sub label">
            shape = type · size ∝ binding hours · hover a node for its constraints
          </div>
        </div>
      )}

      {constraintOverlay && !overviewTypes && (
        <div className="legend__overlay">
          <span className="legend__overlay-dot" />
          <span className="label legend__overlay-text">
            constraints · size ∝ max |SF|
          </span>
        </div>
      )}

      {paneLabel && (
        <div className="legend__pane-label label">{paneLabel}</div>
      )}

      <style>{`
        .legend {
          position: absolute;
          bottom: 88px;
          left: 12px;
          background: rgba(15, 18, 23, 0.9);
          border: 1px solid var(--border);
          border-radius: 4px;
          padding: 8px 10px;
          width: ${BAR_W + 20}px;
          backdrop-filter: blur(4px);
        }
        .legend__title {
          margin-bottom: 5px;
          color: var(--text-secondary);
        }
        .legend__hist {
          height: 22px;
          width: ${BAR_W}px;
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
          width: ${BAR_W}px;
          border-radius: 4px;
          margin-bottom: 3px;
        }
        .legend__labels {
          display: flex;
          justify-content: space-between;
          width: ${BAR_W}px;
        }
        .legend__ticks {
          position: relative;
          width: ${BAR_W}px;
          height: 12px;
        }
        .legend__tick {
          position: absolute;
          top: 0;
          transform: translateX(-50%);
          font-size: 9px;
          opacity: 0.7;
          white-space: nowrap;
        }
        .legend__sub {
          margin-top: 2px;
          width: ${BAR_W}px;
          font-size: 9px;
          opacity: 0.55;
          line-height: 1.3;
        }
        .legend__types {
          margin-top: 6px;
          padding-top: 5px;
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
          font-size: 9px;
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
          font-size: 9px;
          opacity: 0.8;
        }
        .legend__pane-label {
          margin-top: 6px;
          font-family: var(--font-label);
          font-size: 9px;
          letter-spacing: var(--track-label);
          text-transform: uppercase;
          color: var(--text-secondary);
          opacity: 0.75;
        }
      `}</style>
    </div>
  );
}
