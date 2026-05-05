import { useMemo } from "react";
import type { BusState, ViewMode } from "../../api/types";
import {
  FRAGILITY_ANCHORS,
  LMP_PCT_LOW,
  LMP_PCT_HIGH,
  normalizeLmpFromStats,
  DELTA_ANCHORS,
  Z_ANCHORS,
  type LmpStats,
  type BusZStats,
} from "../../lib/colors";

interface Props {
  viewMode: ViewMode;
  buses: BusState[];
  // Window-wide stats. Stable across playback.
  lmpStats: LmpStats | null;
  zStats: BusZStats | null;
}

const HIST_BINS = 24;
const BAR_W = 130;

function formatDollar(v: number): string {
  if (Math.abs(v) >= 1000) return `$${(v / 1000).toFixed(1)}k`;
  return `$${v.toFixed(0)}`;
}

function formatTick(v: number): string {
  if (v === 0) return "0";
  if (v >= 1) return v >= 10 ? v.toFixed(0) : v.toString();
  // Sub-1 values: trim trailing zeros (0.05, 0.1, 0.5)
  return v.toString();
}

export default function Legend({ viewMode, buses, lmpStats, zStats }: Props) {
  const isFragility = viewMode === "fragility";
  const isLmp = viewMode === "lmp";
  const isDelta = viewMode === "delta_rank";
  const isZ = viewMode === "fragility_z";

  // LMP histogram for the *current snapshot*, binned in color-space so each
  // bar aligns directly above the gradient color it falls in.
  const lmpHist = useMemo(() => {
    if (!isLmp || buses.length === 0 || !lmpStats) return null;
    const counts = new Array(HIST_BINS).fill(0);
    for (const b of buses) {
      if (b.lmp == null) continue;
      const norm = normalizeLmpFromStats(b.lmp, lmpStats); // 0..1
      let idx = Math.floor(norm * HIST_BINS);
      if (idx >= HIST_BINS) idx = HIST_BINS - 1;
      if (idx < 0) idx = 0;
      counts[idx] += 1;
    }
    const peak = Math.max(...counts);
    return { counts, peak };
  }, [buses, isLmp, lmpStats]);

  // LMP tick marks: p_low (left), median (center), p_high (right).
  const lmpTicks = useMemo(() => {
    if (!isLmp || !lmpStats) return [];
    return [
      { label: formatDollar(lmpStats.p_low), pct: 0 },
      { label: formatDollar(lmpStats.median), pct: 50 },
      { label: formatDollar(lmpStats.p_high), pct: 100 },
    ];
  }, [isLmp, lmpStats]);

  // Tick positions on the fragility bar.
  const fragilityTicks = useMemo(() => {
    const { floor, red, gamma, red_core, ticks } = FRAGILITY_ANCHORS;
    const logFloor = Math.log10(floor);
    const logRed = Math.log10(red);
    const range = logRed - logFloor;
    return ticks.map((v) => {
      let pct: number;
      if (v <= floor) {
        pct = 0;
      } else if (v <= red) {
        const raw = (Math.log10(v) - logFloor) / range;
        const damped = Math.pow(Math.max(0, raw), gamma);
        pct = Math.min(red_core, red_core * damped) * 100;
      } else {
        const x = Math.log10(v) - logRed;
        const tail = x / (1 + x);
        pct = (red_core + (1 - red_core) * tail) * 100;
      }
      return { value: v, pct };
    });
  }, []);

  // Bar gradient depends on view mode.
  const barGradient = isFragility
    ? "linear-gradient(to right, #22c55e, #eab308, #ef4444)"
    : isLmp
    ? "linear-gradient(to right, #3b82f6, #e2e8d0, #f97316)"
    : isDelta
    ? `linear-gradient(to right, ${DELTA_ANCHORS.purple}, ${DELTA_ANCHORS.cream}, ${DELTA_ANCHORS.teal})`
    : `linear-gradient(to right, ${Z_ANCHORS.gray}, ${Z_ANCHORS.red})`;

  const title = isFragility
    ? "Fragility (log)"
    : isLmp
    ? "LMP ($/MWh)"
    : isDelta
    ? "Δ Rank (fragility − |basis|)"
    : "Fragility z-score";

  return (
    <div className="legend">
      <div className="legend__title label">{title}</div>

      {/* LMP: snapshot histogram against window-wide bin range */}
      {isLmp && lmpHist && (
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

      {/* Tick marks below the bar */}
      {isFragility && (
        <div className="legend__ticks">
          {fragilityTicks.map((t) => (
            <span
              key={t.value}
              className="label mono legend__tick"
              style={{ left: `${t.pct}%` }}
            >
              {formatTick(t.value)}
            </span>
          ))}
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
        </>
      )}

      {isLmp && !lmpStats && (
        <div className="legend__labels">
          <span className="label mono">—</span>
          <span className="label mono">—</span>
        </div>
      )}

      {isDelta && (
        <>
          <div className="legend__labels">
            <span className="label">model under</span>
            <span className="label">over</span>
          </div>
          <div className="legend__sub label">per-snapshot rank</div>
        </>
      )}

      {isZ && (
        <>
          <div className="legend__labels">
            <span className="label mono">≤ typical</span>
            <span className="label mono">+{Z_ANCHORS.saturate}σ</span>
          </div>
          <div className="legend__sub label">
            {zStats ? `per-bus, n=${zStats.perBus.size} buses` : "—"}
          </div>
        </>
      )}

      <div className="legend__lines">
        <div className="legend__line-row">
          <span className="legend__swatch legend__swatch--binding" />
          <span className="label">binding</span>
        </div>
        <div className="legend__line-row">
          <span className="legend__swatch legend__swatch--contingency" />
          <span className="label">N-1 top 5</span>
        </div>
        <div className="legend__line-row">
          <span className="legend__halo-pair">
            <span className="legend__halo legend__halo--pos" />
            <span className="legend__halo legend__halo--neg" />
          </span>
          <span className="label">PTDF ± (line hover)</span>
        </div>
      </div>

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
        .legend__lines {
          margin-top: 8px;
          padding-top: 6px;
          border-top: 1px solid var(--border);
          display: flex;
          flex-direction: column;
          gap: 3px;
        }
        .legend__line-row {
          display: flex;
          align-items: center;
          gap: 6px;
        }
        .legend__swatch {
          width: 18px;
          height: 2px;
          flex-shrink: 0;
        }
        .legend__swatch--binding { background: #ec4899; }
        .legend__swatch--contingency {
          background: repeating-linear-gradient(
            to right, #cbd5e1 0, #cbd5e1 4px, transparent 4px, transparent 7px);
        }
        .legend__halo-pair {
          display: inline-flex;
          gap: 2px;
          width: 18px;
          flex-shrink: 0;
          align-items: center;
          justify-content: center;
        }
        .legend__halo {
          display: inline-block;
          width: 7px;
          height: 7px;
          border-radius: 50%;
          opacity: 0.7;
          filter: blur(0.5px);
        }
        .legend__halo--pos { background: #22d3ee; }
        .legend__halo--neg { background: #fb923c; }
      `}</style>
    </div>
  );
}
