import { useMemo, useRef, useCallback } from "react";
import Tooltip from "../ui/Tooltip";

export interface SparkPoint {
  // Congestion is magnitude, not signed — signed sums cancel visually across
  // strong bidirectional snapshots. λ remains signed in $/MWh.
  forecast_congestion_abs_total: number | null;
  market_congestion_abs_total: number | null;
  system_lambda: number | null;
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

// Forecast blue, ERCOT market congestion yellow, system λ violet.
const FORECAST_CONGESTION_COLOR = "#38bdf8";
const MARKET_CONGESTION_COLOR = "#eab308";
const SYSTEM_LAMBDA_COLOR = "#a78bfa";
// Chrome, not data — routed through the theme tokens. These are applied via the
// `style` prop rather than the `stroke` attribute, because SVG presentation
// attributes do not parse var().
const CURSOR_COLOR = "var(--accent)";
const BASELINE_COLOR = "var(--border)";

// The transport places this in its metadata row, opposite the selected date.
export function TimelineSparklineLegend() {
  return (
    <Tooltip
      as="div"
      className="sparkline__legend"
      placement="bottom"
      tip={
        <>
          Each line is normalized independently within the loaded timeline, so
          its height shows its own shape—not a shared dollar scale. Forecast
          and ERCOT Congestion each run from $0 to that series’ maximum
          Σ|nodal congestion|; ERCOT System λ runs from its observed minimum
          to maximum $/MWh.
        </>
      }
    >
      <span>
        <span
          className="sparkline__sw"
          style={{ background: FORECAST_CONGESTION_COLOR }}
        />
        Forecast Congestion
      </span>
      <span>
        <span className="sparkline__sw" style={{ background: MARKET_CONGESTION_COLOR }} />
        ERCOT Congestion
      </span>
      <span>
        <span className="sparkline__sw" style={{ background: SYSTEM_LAMBDA_COLOR }} />
        ERCOT System λ
      </span>
    </Tooltip>
  );
}

export default function TimelineSparkline({
  series,
  currentIndex,
  onSeek,
  height = 22,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);

  // Each signal has different units and scale, so render its shape normalized
  // to its own observed range. Missing values make a visible gap, rather than
  // implying a zero observation.
  const geometry = useMemo(() => {
    if (series.length === 0) {
      return { forecastPath: "", marketPath: "", lambdaPath: "" };
    }

    const innerH = 100; // viewBox y range; CSS scales to actual px
    const usableH = innerH - PAD_TOP - PAD_BOTTOM;

    // x position for index i, centered in its slot.
    const xAt = (i: number) =>
      series.length === 1 ? VIEW_W / 2 : (i / (series.length - 1)) * VIEW_W;

    // y position from a [0..1] normalized value (0 = bottom, 1 = top).
    const yFrom = (norm: number) =>
      innerH - PAD_BOTTOM - usableH * Math.max(0, Math.min(1, norm));

    const linePath = (
      values: Array<number | null>,
      normalize: (value: number) => number
    ) => {
      let path = "";
      let inSegment = false;
      values.forEach((value, i) => {
        if (value == null) {
          inSegment = false;
          return;
        }
        const command = inSegment ? "L" : "M";
        path += `${command} ${xAt(i).toFixed(1)} ${yFrom(normalize(value)).toFixed(1)} `;
        inSegment = true;
      });
      return path;
    };
    const congestionPath = (values: Array<number | null>) => {
      const defined = values.filter((value): value is number => value != null);
      const peak = Math.max(0, ...defined);
      return linePath(values, (value) => value / (peak || 1));
    };
    const lambdaValues = series.map((p) => p.system_lambda);
    const definedLambda = lambdaValues.filter((value): value is number => value != null);
    const lambdaMin = Math.min(...definedLambda);
    const lambdaMax = Math.max(...definedLambda);

    return {
      forecastPath: congestionPath(series.map((p) => p.forecast_congestion_abs_total)),
      marketPath: congestionPath(series.map((p) => p.market_congestion_abs_total)),
      lambdaPath: linePath(
        lambdaValues,
        (value) => lambdaMax === lambdaMin ? 0.5 : (value - lambdaMin) / (lambdaMax - lambdaMin)
      ),
    };
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

        {/* All three paths are normalized independently. */}
        <path
          d={geometry.forecastPath}
          fill="none"
          stroke={FORECAST_CONGESTION_COLOR}
          strokeWidth={1.25}
          strokeDasharray="3 2"
          vectorEffect="non-scaling-stroke"
        />
        <path
          d={geometry.marketPath}
          fill="none"
          stroke={MARKET_CONGESTION_COLOR}
          strokeWidth={1.25}
          vectorEffect="non-scaling-stroke"
        />
        <path
          d={geometry.lambdaPath}
          fill="none"
          stroke={SYSTEM_LAMBDA_COLOR}
          strokeWidth={1.25}
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
    </div>
  );
}
