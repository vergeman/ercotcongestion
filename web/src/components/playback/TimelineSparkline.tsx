import { useMemo, useRef, useCallback } from "react";

export interface SparkPoint {
  // magnitude, not signed — signed sums cancel visually across strong
  // bidirectional snapshots.
  modeled_congestion_abs_total: number | null;
}

interface Props {
  series: SparkPoint[];
  currentIndex: number;
  onSeek: (index: number) => void;
  height?: number;
}

const VIEW_W = 1000; // viewBox width — gets stretched horizontally
const PAD_TOP = 4; // px space at top of viewBox
const PAD_BOTTOM = 4; // px space at bottom of viewBox

// Colors — match the rest of the app (yellow=‖modeled congestion‖).
const MC_ABS_COLOR = "#eab308";
// Chrome, not data — routed through the theme tokens. These are applied via the
// `style` prop rather than the `stroke` attribute, because SVG presentation
// attributes do not parse var().
const CURSOR_COLOR = "var(--accent)";
const BASELINE_COLOR = "var(--border)";

export default function TimelineSparkline({
  series,
  currentIndex,
  onSeek,
  height = 22,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);

  // Compute the peak and the SVG geometry once per series change. The signal
  // is normalized to its own peak. ‖modeled congestion‖ renders as a filled area.
  const geometry = useMemo(() => {
    if (series.length === 0) {
      return { areaPath: "", peakMc: 0 };
    }

    const innerH = 100; // viewBox y range; CSS scales to actual px
    const usableH = innerH - PAD_TOP - PAD_BOTTOM;

    let peakMc = 0;
    for (const p of series) {
      if (
        p.modeled_congestion_abs_total != null &&
        p.modeled_congestion_abs_total > peakMc
      ) {
        peakMc = p.modeled_congestion_abs_total;
      }
    }
    // Avoid /0 when a window has no signal at all.
    const mcNorm = peakMc > 0 ? peakMc : 1;

    // x position for index i, centered in its slot.
    const xAt = (i: number) =>
      series.length === 1 ? VIEW_W / 2 : (i / (series.length - 1)) * VIEW_W;

    // y position from a [0..1] normalized value (0 = bottom, 1 = top).
    const yFrom = (norm: number) =>
      innerH - PAD_BOTTOM - usableH * Math.max(0, Math.min(1, norm));

    // ‖Modeled Congestion‖ area path
    let areaPath = `M 0 ${innerH - PAD_BOTTOM} `;
    series.forEach((p, i) => {
      const x = xAt(i);
      const y = yFrom((p.modeled_congestion_abs_total ?? 0) / mcNorm);
      areaPath += `L ${x.toFixed(1)} ${y.toFixed(1)} `;
    });
    areaPath += `L ${VIEW_W} ${innerH - PAD_BOTTOM} Z`;

    return { areaPath, peakMc };
  }, [series]);

  // Click/drag to seek. We translate the click X to the nearest series index.
  const handleSeekFromEvent = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      const svg = svgRef.current;
      if (!svg || series.length === 0) return;
      const rect = svg.getBoundingClientRect();
      const ratio = (e.clientX - rect.left) / rect.width;
      const idx = Math.round(ratio * (series.length - 1));
      const clamped = Math.max(0, Math.min(series.length - 1, idx));
      onSeek(clamped);
    },
    [series.length, onSeek]
  );

  const cursorX =
    series.length <= 1
      ? VIEW_W / 2
      : (currentIndex / (series.length - 1)) * VIEW_W;

  if (series.length === 0) {
    return (
      <div
        className="sparkline sparkline--empty"
        style={{ height: height + 12 }}
      />
    );
  }

  return (
    <div className="sparkline">
      {/* legend row above the chart, top-right aligned */}
      <div className="sparkline__legend">
        <span>
          <span
            className="sparkline__sw"
            style={{
              background: MC_ABS_COLOR,
              opacity: 0.6,
              height: 6,
            }}
          />
          ‖modeled congestion‖
        </span>
      </div>

      <svg
        ref={svgRef}
        viewBox={`0 0 ${VIEW_W} 100`}
        preserveAspectRatio="none"
        width="100%"
        height={height}
        onClick={handleSeekFromEvent}
        style={{ cursor: "pointer", display: "block" }}
      >
        {/* baseline */}
        <line
          x1={0}
          y1={100 - PAD_BOTTOM}
          x2={VIEW_W}
          y2={100 - PAD_BOTTOM}
          style={{ stroke: BASELINE_COLOR }}
          strokeWidth={0.5}
          vectorEffect="non-scaling-stroke"
        />

        {/* ‖modeled congestion‖ area */}
        <path
          d={geometry.areaPath}
          fill={MC_ABS_COLOR}
          fillOpacity={0.25}
          stroke={MC_ABS_COLOR}
          strokeWidth={1}
          vectorEffect="non-scaling-stroke"
        />

        {/* current-position cursor */}
        <line
          x1={cursorX}
          y1={0}
          x2={cursorX}
          y2={100}
          style={{ stroke: CURSOR_COLOR }}
          strokeWidth={1}
          strokeDasharray="2 2"
          vectorEffect="non-scaling-stroke"
        />
      </svg>

      <style>{`
        .sparkline {
          position: relative;
          width: 100%;
          flex-shrink: 0;
        }
        .sparkline--empty {
          opacity: 0.2;
        }
        .sparkline__legend {
          display: flex;
          justify-content: flex-end;
          gap: 10px;
          font-size: var(--fs-micro);
          color: var(--text-muted);
          font-family: var(--font-mono);
          line-height: 1;
          margin-bottom: 2px;
        }
        .sparkline__sw {
          display: inline-block;
          width: 8px;
          vertical-align: middle;
          margin-right: 3px;
        }
      `}</style>
    </div>
  );
}
