import { useMemo, useRef, useCallback } from "react";

export interface SparkPoint {
  fragility_total: number | null;
  n_binding_lines: number | null;
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

// Colors — match the rest of the app (yellow=fragility, pink=binding).
const FRAGILITY_COLOR = "#eab308";
const BINDING_COLOR = "#ec4899";
const CURSOR_COLOR = "#38bdf8";
const BASELINE_COLOR = "#252d3a";

export default function TimelineSparkline({
  series,
  currentIndex,
  onSeek,
  height = 22,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);

  // Compute peaks and the SVG geometry once per series change. Both signals
  // are normalized to their own peak — true dual-axis. fragility renders as
  // a filled area; binding_lines renders as a step line on top.
  const geometry = useMemo(() => {
    if (series.length === 0) {
      return { areaPath: "", stepPath: "", peakFrag: 0, peakBinding: 0 };
    }

    const innerH = 100; // viewBox y range; CSS scales to actual px
    const usableH = innerH - PAD_TOP - PAD_BOTTOM;

    let peakFrag = 0;
    let peakBinding = 0;
    for (const p of series) {
      if (p.fragility_total != null && p.fragility_total > peakFrag) {
        peakFrag = p.fragility_total;
      }
      if (p.n_binding_lines != null && p.n_binding_lines > peakBinding) {
        peakBinding = p.n_binding_lines;
      }
    }
    // Avoid /0 when a window has no signal at all.
    const fragNorm = peakFrag > 0 ? peakFrag : 1;
    const bindNorm = peakBinding > 0 ? peakBinding : 1;

    // x position for index i, centered in its slot.
    const xAt = (i: number) =>
      series.length === 1 ? VIEW_W / 2 : (i / (series.length - 1)) * VIEW_W;

    // y position from a [0..1] normalized value (0 = bottom, 1 = top).
    const yFrom = (norm: number) =>
      innerH - PAD_BOTTOM - usableH * Math.max(0, Math.min(1, norm));

    // Fragility area path
    let areaPath = `M 0 ${innerH - PAD_BOTTOM} `;
    series.forEach((p, i) => {
      const x = xAt(i);
      const y = yFrom((p.fragility_total ?? 0) / fragNorm);
      areaPath += `L ${x.toFixed(1)} ${y.toFixed(1)} `;
    });
    areaPath += `L ${VIEW_W} ${innerH - PAD_BOTTOM} Z`;

    // Binding-lines step path (squared corners, like the mockup)
    let stepPath = "";
    series.forEach((p, i) => {
      const x = xAt(i);
      const y = yFrom((p.n_binding_lines ?? 0) / bindNorm);
      if (i === 0) {
        stepPath += `M ${x.toFixed(1)} ${y.toFixed(1)} `;
      } else {
        const prevY = yFrom((series[i - 1].n_binding_lines ?? 0) / bindNorm);
        stepPath += `L ${x.toFixed(1)} ${prevY.toFixed(1)} L ${x.toFixed(
          1
        )} ${y.toFixed(1)} `;
      }
    });

    return { areaPath, stepPath, peakFrag, peakBinding };
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
              background: FRAGILITY_COLOR,
              opacity: 0.6,
              height: 6,
            }}
          />
          fragility
        </span>
        <span>
          <span
            className="sparkline__sw"
            style={{ background: BINDING_COLOR, height: 1.5 }}
          />
          binding
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
          stroke={BASELINE_COLOR}
          strokeWidth={0.5}
          vectorEffect="non-scaling-stroke"
        />

        {/* fragility area */}
        <path
          d={geometry.areaPath}
          fill={FRAGILITY_COLOR}
          fillOpacity={0.25}
          stroke={FRAGILITY_COLOR}
          strokeWidth={1}
          vectorEffect="non-scaling-stroke"
        />

        {/* binding lines step */}
        <path
          d={geometry.stepPath}
          fill="none"
          stroke={BINDING_COLOR}
          strokeWidth={1.5}
          vectorEffect="non-scaling-stroke"
        />

        {/* current-position cursor */}
        <line
          x1={cursorX}
          y1={0}
          x2={cursorX}
          y2={100}
          stroke={CURSOR_COLOR}
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
          font-size: 9px;
          color: var(--text-muted, #64748b);
          font-family: var(--text-mono, monospace);
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
