import { useMemo } from "react";
import { cssVar, useTheme } from "../../lib/theme";
import { formatDollar } from "../../lib/format";
import Tooltip from "../ui/Tooltip";
import type { SpRow, MapDataMode } from "../../api/types";
import {
  normalizeLmp,
  localExtremeThreshold,
  EXTREME_PRICE_THRESHOLD,
  LMP_SCALE_CONTROLS,
  CONGESTION_SCALE_CONTROLS,
  normalizeCongestion,
  congestionAlarmColor,
  congestionColor,
  lmpColor,
  type LmpStats,
  type CongestionStats,
} from "../../lib/colors";

interface Props {
  dataMode: MapDataMode;
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
  // The constraints-overlay on/off control itself (0130): rendered only on panes
  // that carry the overlay.
  constraintsToggle?: { checked: boolean; onChange: (v: boolean) => void };
  // True when the current hour's predicted LMP used the persistence-λ fallback
  // (no DAM system-λ published yet for this hour) rather than a settled value —
  // a display-only provenance marker (0130), never a graded signal. Only
  // meaningful on a forecast pane's `lmp` legend.
  lambdaIndicative?: boolean;
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
  {
    label: "Transmission — corridor",
    mark: "corridor",
    token: "--sf-transmission",
  },
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
        <rect
          x="1"
          y="2"
          width="16"
          height="8"
          rx="4"
          fill={color}
          opacity="0.85"
        />
      )}
      {mark === "corridor" && (
        <>
          <line x1="2" y1="6" x2="16" y2="6" stroke={color} strokeWidth="2" />
          <circle cx="2" cy="6" r="2" fill={color} />
          <circle cx="16" cy="6" r="2" fill={color} />
        </>
      )}
      {mark === "point" && (
        <circle
          cx="9"
          cy="6"
          r="4"
          fill="none"
          stroke={color}
          strokeWidth="2"
        />
      )}
    </svg>
  );
}

function AggregateMark({ label }: { label: "H" | "Z" }) {
  return (
    <span className="legend__aggregate-mark-box" aria-hidden="true">
      <span
        className={`legend__aggregate-mark legend__aggregate-mark--${label === "H" ? "hub" : "load-zone"} mono`}
      >
        <span className="legend__aggregate-mark-label">{label}</span>
      </span>
    </span>
  );
}

const HIST_BINS = 24;
// Leave room for a compact set of dollar ticks without turning the overlay into
// a side panel.
const BAR_W = 280;

type LegendTick = { value: number; pct: number };
type LegendDomain = { start: number; end: number };

function anchorsFor(isCongestion: boolean): number[] {
  if (!isCongestion) return LMP_SCALE_CONTROLS.map(([value]) => value);
  return [
    ...CONGESTION_SCALE_CONTROLS.slice(1).map(([value]) => -value).reverse(),
    0,
    ...CONGESTION_SCALE_CONTROLS.map(([value]) => value),
  ];
}

function legendDomain(min: number, max: number, isCongestion: boolean): LegendDomain {
  const anchors = anchorsFor(isCongestion);
  const start = [...anchors].reverse().find((value) => value <= min) ?? anchors[0];
  const end = anchors.find((value) => value >= max) ?? anchors[anchors.length - 1];
  return { start, end };
}

function colorPosition(value: number, isCongestion: boolean): number {
  return isCongestion ? (normalizeCongestion(value) + 1) / 2 : normalizeLmp(value);
}

function slicePosition(value: number, domainSlice: LegendDomain, isCongestion: boolean): number {
  const start = colorPosition(domainSlice.start, isCongestion);
  const end = colorPosition(domainSlice.end, isCongestion);
  const span = end - start;
  // The neutral congestion plateau intentionally shares one color position.
  if (Math.abs(span) < 1e-9) {
    return ((value - domainSlice.start) / (domainSlice.end - domainSlice.start || 1)) * 100;
  }
  return ((colorPosition(value, isCongestion) - start) / span) * 100;
}

function legendTicks(domainSlice: LegendDomain, isCongestion: boolean): LegendTick[] {
  const { start, end } = domainSlice;
  const anchors = anchorsFor(isCongestion);
  const candidates = anchors.filter((value) => value >= start && value <= end);
  const reference = isCongestion ? 0 : 25;
  const extreme = start <= EXTREME_PRICE_THRESHOLD && end >= EXTREME_PRICE_THRESHOLD
    ? EXTREME_PRICE_THRESHOLD
    : null;
  const ordered = [start, end, reference, 0, extreme]
    .filter((value): value is number => value != null && value >= start && value <= end)
    .concat(candidates.filter((value) => value !== start && value !== end && value !== reference && value !== extreme)
      .sort((a, b) => Math.abs(a - (start + end) / 2) - Math.abs(b - (start + end) / 2)));
  const selected: number[] = [];
  const width = (value: number) => tickLabel(value, isCongestion).length * 7 + 6;
  const fits = (value: number) => {
    const center = (slicePosition(value, domainSlice, isCongestion) / 100) * BAR_W;
    const half = width(value) / 2;
    const left = value === start ? 0 : value === end ? BAR_W - width(value) : center - half;
    const right = left + width(value);
    return selected.every((other) => {
      const otherCenter = (slicePosition(other, domainSlice, isCongestion) / 100) * BAR_W;
      const otherLeft = other === start ? 0 : other === end ? BAR_W - width(other) : otherCenter - width(other) / 2;
      return right + 4 <= otherLeft || left >= otherLeft + width(other) + 4;
    });
  };
  for (const value of ordered) {
    if (selected.length === 5 || selected.includes(value) || !fits(value)) continue;
    selected.push(value);
  }
  selected.sort((a, b) => a - b);
  return selected.map((value) => ({ value, pct: slicePosition(value, domainSlice, isCongestion) }));
}

function tickLabel(value: number, signed: boolean): string {
  return signed && value > 0 ? `+${formatDollar(value)}` : formatDollar(value);
}

function slicedGradient(domainSlice: LegendDomain, congestion: boolean): string {
  const { start, end } = domainSlice;
  if (start === end) return congestion ? congestionColor(0) : lmpColor(normalizeLmp(start));
  const values = [start, ...anchorsFor(congestion).filter((value) => value > start && value < end), end];
  const stops = values.map((value) => {
    const color = congestion
      ? congestionColor(normalizeCongestion(value))
      : lmpColor(normalizeLmp(value));
    return `${color} ${slicePosition(value, domainSlice, congestion)}%`;
  });
  return `linear-gradient(to right, ${stops.join(", ")})`;
}

export default function Legend({
  dataMode,
  rows,
  lmpStats,
  mcStats,
  titleOverride,
  signLabels,
  barGradientOverride,
  constraintOverlay = false,
  overviewTypes = false,
  constraintsToggle,
  lambdaIndicative = false,
}: Props) {
  // Subscribes the legend to theme flips so the cssVar() type-mark lookups below
  // re-resolve (SVG presentation attributes cannot take var()).
  const theme = useTheme();
  const isCongestion = dataMode === "congestion";
  const isLmp = dataMode === "lmp";

  // Snapshot distribution, binned in color-space so each bar sits directly above
  // the gradient color its values fall in. Computed for BOTH palettes (LMP off
  // spp, congestion off the signed value mapped through the same diverging
  // normalization the map uses) so every legend carries the distribution.
  const domainSlice = useMemo(() => {
    const stats = isCongestion ? mcStats : lmpStats;
    return stats?.n ? legendDomain(stats.min, stats.max, isCongestion) : null;
  }, [isCongestion, lmpStats, mcStats]);

  const ticks = useMemo(() => {
    return domainSlice ? legendTicks(domainSlice, isCongestion) : [];
  }, [domainSlice, isCongestion]);

  const hist = useMemo(() => {
    if (rows.length === 0) return null;
    if (!domainSlice) return null;
    const counts = new Array(HIST_BINS).fill(0);
    let n = 0;
    if (isLmp && lmpStats) {
      for (const r of rows) {
        if (r.spp == null) continue;
        let idx = Math.floor((slicePosition(r.spp, domainSlice, false) / 100) * HIST_BINS);
        if (idx >= HIST_BINS) idx = HIST_BINS - 1;
        if (idx < 0) idx = 0;
        counts[idx] += 1;
        n += 1;
      }
    } else if (isCongestion && mcStats) {
      for (const r of rows) {
        if (r.congestion == null) continue;
        let idx = Math.floor((slicePosition(r.congestion, domainSlice, true) / 100) * HIST_BINS);
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
  }, [rows, isLmp, isCongestion, lmpStats, mcStats, domainSlice]);

  // Built from the palette functions so the bar tracks the theme (light gets the
  // grey center + deepened ends); useTheme() above re-renders on a flip.
  const barGradient =
    barGradientOverride ??
    (domainSlice && slicedGradient(domainSlice, isCongestion)) ??
    (isCongestion
      ? `linear-gradient(to right, ${congestionColor(-1)}, ${congestionColor(0)}, ${congestionColor(1)})`
      : `linear-gradient(to right, ${lmpColor(0)}, ${lmpColor(0.5)}, ${lmpColor(1)})`);

  // Title splits into a name (own line) and the quantity/equation (own line,
  // smaller). Built-ins carry both explicitly; an override is split on " · ".
  let titleName: string;
  let titleEq: string;
  if (titleOverride) {
    const dot = titleOverride.indexOf(" · ");
    titleName = dot >= 0 ? titleOverride.slice(0, dot) : titleOverride;
    titleEq = dot >= 0 ? titleOverride.slice(dot + 3) : "";
  } else if (isCongestion) {
    titleName = "Congestion";
    titleEq = "SPP − λ ($/MWh)";
  } else {
    titleName = "DAM SPP / LMP";
    titleEq = "($/MWh)";
  }
  const negLabel = signLabels?.neg ?? "Export";
  const posLabel = signLabels?.pos ?? "Import";
  const alarmThreshold = useMemo(
    () => localExtremeThreshold(
      rows.map((row) => isCongestion ? row.congestion : row.spp),
      isCongestion
    ),
    [isCongestion, rows]
  );
  // Halos are a per-frame local-outlier cue.  The $500 threshold merely gates
  // whether this hour's highest 1% receives the cue; it is not an absolute
  // rule that every value above $500 gets a halo. Keep the key present when
  // inactive so its appearance never shifts the legend's layout.
  const extremePrice = isCongestion && mcStats
    ? {
        color: congestionAlarmColor(theme),
        active: alarmThreshold != null,
      }
    : isLmp && lmpStats
    ? {
        color: lmpColor(1, theme),
        active: alarmThreshold != null,
      }
    : null;
  const extremePriceTip = extremePrice?.active
    ? `Highlights the highest-priced 1% of nodes at the current hour, only when their cutoff is at least $${EXTREME_PRICE_THRESHOLD}/MWh. The highlighted nodes may change as playback advances.`
    : `No local outlier halos at this hour. Halos highlight the highest-priced 1% of nodes only when their cutoff is at least $${EXTREME_PRICE_THRESHOLD}/MWh.`;

  return (
    <div className="legend">
      <div className="legend__title label">{titleName}</div>
      {titleEq && <div className="legend__eq label">{titleEq}</div>}
      {/* Persistence-λ provenance (0130): the predicted LMP this hour used the
          most recent settled day's λ curve, not a settled DAM value — display
          only, never a graded signal. */}
      {isLmp && lambdaIndicative && (
        <div className="legend__indicative label">Indicative — persisted λ</div>
      )}

      {/* Snapshot distribution over the cursor-day bin range, on every legend. */}
      {hist && (
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

      <div className="legend__bar" style={{ background: barGradient }} />

      {isCongestion && mcStats && (
        <>
          <div className="legend__ticks">
            {ticks.map((tick) => <span key={tick.value} className={`label mono legend__tick${tick.pct === 0 ? " legend__tick--start" : tick.pct === 100 ? " legend__tick--end" : ""}`} style={tick.pct === 0 || tick.pct === 100 ? undefined : { left: `${tick.pct}%` }}>{tickLabel(tick.value, true)}</span>)}
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
          {ticks.map((t) => (
            <span
              key={t.value}
              className={`label mono legend__tick${
                t.pct === 0
                  ? " legend__tick--start"
                  : t.pct === 100
                  ? " legend__tick--end"
                  : ""
              }`}
              style={
                t.pct === 0 || t.pct === 100 ? undefined : { left: `${t.pct}%` }
              }
            >
              {tickLabel(t.value, false)}
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

      {extremePrice && (
        <Tooltip
          as="div"
          className="legend__alarm"
          tip={extremePriceTip}
        >
          <span
            className={`legend__alarm-swatch${extremePrice.active ? "" : " legend__alarm-swatch--inactive"}`}
            style={{ backgroundColor: extremePrice.color }}
          />
          <span className="label legend__alarm-text">Extreme 1% prices</span>
        </Tooltip>
      )}

      {/* Constraints-overlay control (0130): lives on the pane that draws it. */}
      {constraintsToggle && (
        <label className="legend__toggle">
          <input
            type="checkbox"
            checked={constraintsToggle.checked}
            onChange={(e) => constraintsToggle.onChange(e.target.checked)}
          />
          <span className="label legend__toggle-text">Constraints overlay</span>
        </label>
      )}

      <div className="legend__types">
        {overviewTypes &&
          OVERVIEW_TYPES.map((t) => (
            <div key={t.mark} className="legend__type-row">
              <TypeMark mark={t.mark} color={cssVar(t.token)} />
              <span className="label legend__type-text">{t.label}</span>
            </div>
          ))}
        <div className="legend__type-row">
          <AggregateMark label="H" />
          <span className="label legend__type-text">Hub</span>
        </div>
        <div className="legend__type-row">
          <AggregateMark label="Z" />
          <span className="label legend__type-text">Load zone</span>
        </div>
      </div>

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
        .legend__indicative {
          margin-top: -3px;
          margin-bottom: 7px;
          font-size: var(--fs-label);
          color: var(--accent);
        }
        .legend__toggle {
          display: flex;
          align-items: center;
          gap: 6px;
          margin-top: 9px;
          padding-top: 9px;
          border-top: 1px solid var(--border);
          cursor: pointer;
        }
        .legend__toggle-text {
          font-size: var(--fs-label);
          opacity: 0.85;
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
        .legend__tick::before {
          content: "";
          position: absolute;
          top: -6px;
          left: 50%;
          width: 1px;
          height: 4px;
          background: var(--text-muted);
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
        .legend__tick--start::before {
          left: 0;
        }
        .legend__tick--end::before {
          left: auto;
          right: 0;
        }
        .legend__alarm {
          display: flex;
          align-items: center;
          gap: 6px;
          margin-top: 7px;
          padding-top: 7px;
          border-top: 1px solid var(--border);
        }
        .legend__alarm-swatch {
          width: 11px;
          height: 11px;
          border-radius: 50%;
          border: 1px solid var(--map-aggregate-label);
          flex: 0 0 11px;
          /* Mirrors the map's extreme-price pulse (GridMap ALARM_PULSE_*): a
             1.4s raised-cosine fade between 0.28 and full so the legend key
             breathes in step with the outlier nodes. */
          animation: legend-alarm-pulse 1.4s ease-in-out infinite;
        }
        .legend__alarm-swatch--inactive {
          animation: none;
          opacity: 0.35;
        }
        @keyframes legend-alarm-pulse {
          0%,
          100% {
            opacity: 0.28;
          }
          50% {
            opacity: 1;
          }
        }
        @media (prefers-reduced-motion: reduce) {
          .legend__alarm-swatch {
            animation: none;
          }
        }
        .legend__alarm-text {
          font-size: var(--fs-label);
          opacity: 0.9;
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
          margin-bottom: 6px;
        }
        .legend__type-svg {
          flex-shrink: 0;
        }
        .legend__type-text {
          font-size: var(--fs-label);
          opacity: 0.85;
        }
        .legend__aggregate-mark {
          display: grid;
          place-items: center;
          width: 16px;
          height: 16px;
          border: 1px solid var(--map-aggregate-label);
          border-radius: 50%;
          color: var(--map-aggregate-label);
          font-size: 11px;
          font-weight: 600;
          line-height: 1;
        }
        .legend__aggregate-mark--load-zone {
          /* A rotated square's diagonal is √2 larger than its side. Reducing
             the side keeps the diamond's visible footprint aligned with the
             16px circular Hub mark. */
          width: 12px;
          height: 12px;
          border-radius: 0;
          transform: rotate(45deg);
        }
        .legend__aggregate-mark--load-zone .legend__aggregate-mark-label {
          font-size: 9px;
          transform: rotate(-45deg);
        }
        .legend__aggregate-mark--hub .legend__aggregate-mark-label {
          font-size: 10px;
        }
        /* Light mode keeps the original near-black outline. In dark mode the
           same unfilled treatment needs its colour inverted to remain visible
           over the legend panel. */
        :root:not([data-theme='light']) .legend__aggregate-mark {
          border-color: var(--map-node-idle);
          color: var(--text-primary);
        }
        .legend__aggregate-mark-box {
          display: grid;
          place-items: center;
          width: 18px;
          flex: 0 0 18px;
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
