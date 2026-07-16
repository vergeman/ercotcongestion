import { useMemo } from "react";
import type { SpRow, ViewMode } from "../../api/types";
import {
  LMP_PCT_LOW,
  LMP_PCT_HIGH,
  normalizeLmpFromStats,
  type LmpStats,
  type ModeledCongestionStats,
} from "../../lib/colors";

interface Props {
  viewMode: ViewMode;
  rows: SpRow[];
  // Window-wide stats. Stable across playback.
  lmpStats: LmpStats | null;
  mcStats: ModeledCongestionStats | null;
  // "full" (default): palette + histogram/ticks. "palette-only": palette +
  // ticks/labels/sub only — used on the placeholder (prediction) pane.
  variant?: "full" | "palette-only";
  // Optional caption under the palette; distinguishes the two panes.
  paneLabel?: string;
  // When set, appends a constraint-overlay key (violet marker, size ∝ max|SF|).
  // Shown only on the pane that carries the overlay, and only while it's on.
  constraintOverlay?: boolean;
}

const HIST_BINS = 24;
const BAR_W = 130;

function formatDollar(v: number): string {
  if (Math.abs(v) >= 1000) return `$${(v / 1000).toFixed(1)}k`;
  return `$${v.toFixed(0)}`;
}

export default function Legend({
  viewMode,
  rows,
  lmpStats,
  mcStats,
  variant = "full",
  paneLabel,
  constraintOverlay = false,
}: Props) {
  const isCongestion = viewMode === "congestion";
  const isLmp = viewMode === "lmp";
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

  const barGradient = isCongestion
    ? "linear-gradient(to right, rgb(59,130,246), rgb(232,226,215), rgb(239,68,68))"
    : "linear-gradient(to right, #3b82f6, #e2e8d0, #f97316)";

  const title = isCongestion
    ? "Congestion · SPP − λ ($/MWh)"
    : "DAM SPP / LMP ($/MWh)";

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

      <div className="legend__bar" style={{ background: barGradient }} />

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
            <span className="label">export (−)</span>
            <span className="label">import (+)</span>
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

      {constraintOverlay && (
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
          font-size: 9px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          color: var(--text-secondary);
          opacity: 0.75;
        }
      `}</style>
    </div>
  );
}
