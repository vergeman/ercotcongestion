import { useMemo } from "react";
import type { BusState, ViewMode } from "../../api/types";
import {
  LMP_PCT_LOW,
  LMP_PCT_HIGH,
  normalizeLmpFromStats,
  DELTA_ANCHORS,
  BINDING_PROXIMITY_ANCHORS,
  clusterColor,
  type LmpStats,
  type ModeledCongestionStats,
} from "../../lib/colors";

interface Props {
  viewMode: ViewMode;
  buses: BusState[];
  // Window-wide stats. Stable across playback.
  lmpStats: LmpStats | null;
  mcStats: ModeledCongestionStats | null;
  // Zones layer state (S3.2). Toggle button lives in the legend so the
  // palette panel and layer switch stay adjacent.
  showZones: boolean;
  onToggleZones: () => void;
  tightClusterIds: Set<number>;
}

const HIST_BINS = 24;
const BAR_W = 130;

function formatDollar(v: number): string {
  if (Math.abs(v) >= 1000) return `$${(v / 1000).toFixed(1)}k`;
  return `$${v.toFixed(0)}`;
}

export default function Legend({
  viewMode,
  buses,
  lmpStats,
  mcStats,
  showZones,
  onToggleZones,
  tightClusterIds,
}: Props) {
  const isModeledCongestion = viewMode === "modeled_congestion";
  const isLmp = viewMode === "lmp";
  const isDelta = viewMode === "congestion_vs_basis";
  const isProximity = viewMode === "binding_proximity";

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

  // Bar gradient depends on view mode.
  const barGradient = isModeledCongestion
    ? "linear-gradient(to right, rgb(59,130,246), rgb(232,226,215), rgb(239,68,68))"
    : isLmp
    ? "linear-gradient(to right, #3b82f6, #e2e8d0, #f97316)"
    : isDelta
    ? `linear-gradient(to right, ${DELTA_ANCHORS.purple}, ${DELTA_ANCHORS.cream}, ${DELTA_ANCHORS.teal})`
    : "linear-gradient(to right, rgb(30,41,59), rgb(234,179,8), rgb(239,68,68))";

  const title = isModeledCongestion
    ? "Modeled Congestion ($/MWh)"
    : isLmp
    ? "LMP ($/MWh)"
    : isDelta
    ? "Δ Rank (modeled congestion − basis)"
    : "Binding Proximity";

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

      {/* Modeled congestion: signed diverging; center = 0, edges = ±p_high */}
      {isModeledCongestion && mcStats && (
        <>
          <div className="legend__ticks">
            <span
              className="label mono legend__tick"
              style={{ left: "0%" }}
            >
              −{formatDollar(mcStats.p_high)}
            </span>
            <span
              className="label mono legend__tick"
              style={{ left: "50%" }}
            >
              0
            </span>
            <span
              className="label mono legend__tick"
              style={{ left: "100%" }}
            >
              +{formatDollar(mcStats.p_high)}
            </span>
          </div>
          <div className="legend__labels">
            <span className="label">export (−)</span>
            <span className="label">import (+)</span>
          </div>
          <div className="legend__sub label">
            window |max| {formatDollar(mcStats.max_abs)} · anchor = |mc| P99
          </div>
        </>
      )}

      {isModeledCongestion && !mcStats && (
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
          <div className="legend__sub label">per-snapshot signed rank</div>
        </>
      )}

      {isProximity && (
        <>
          <div className="legend__ticks">
            {BINDING_PROXIMITY_ANCHORS.ticks.map((v) => (
              <span
                key={v}
                className="label mono legend__tick"
                style={{ left: `${v * 100}%` }}
              >
                {v.toFixed(v < 1 ? 1 : 0)}
              </span>
            ))}
          </div>
          <div className="legend__sub label">0 slack, 1 binding</div>
        </>
      )}

      <div className="legend__zones">
        <button
          type="button"
          className={
            "legend__zones-toggle label" + (showZones ? " active" : "")
          }
          onClick={onToggleZones}
        >
          {showZones ? "Zones ✓" : "Zones"}
        </button>
        {showZones && tightClusterIds.size > 0 && (
          <div className="legend__zones-swatches">
            {Array.from(tightClusterIds)
              .sort((a, b) => a - b)
              .map((cid) => (
                <span key={cid} className="legend__zone-swatch">
                  <span
                    className="legend__zone-dot"
                    style={{ background: clusterColor(cid, tightClusterIds) }}
                  />
                  <span className="label mono">Z{cid}</span>
                </span>
              ))}
          </div>
        )}
      </div>

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

        .legend__zones {
          margin-top: 8px;
          padding-top: 6px;
          border-top: 1px solid var(--border);
          display: flex;
          flex-direction: column;
          gap: 5px;
        }
        .legend__zones-toggle {
          align-self: flex-start;
          background: transparent;
          color: var(--text-secondary);
          border: 1px solid var(--border);
          border-radius: 3px;
          padding: 3px 8px;
          font-family: 'Barlow Condensed', sans-serif;
          font-weight: 600;
          font-size: 10px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          cursor: pointer;
        }
        .legend__zones-toggle:hover { color: var(--accent); }
        .legend__zones-toggle.active {
          color: var(--accent);
          border-color: var(--accent);
        }
        .legend__zones-swatches {
          display: flex;
          flex-wrap: wrap;
          gap: 3px 8px;
        }
        .legend__zone-swatch {
          display: inline-flex;
          align-items: center;
          gap: 4px;
        }
        .legend__zone-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          display: inline-block;
        }
      `}</style>
    </div>
  );
}
