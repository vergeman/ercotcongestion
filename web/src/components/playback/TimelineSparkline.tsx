import { useMemo, useRef, useCallback } from "react";
import Tooltip from "../ui/Tooltip";

export interface SparkPoint {
  // Congestion totals use magnitude so import and export values do not cancel.
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

const VIEW_W = 1000;
const PAD_TOP = 4;
const PAD_BOTTOM = 4;

// Forecast blue, ERCOT congestion yellow, system λ violet.
const FORECAST_CONGESTION_COLOR = "#38bdf8";
const MARKET_CONGESTION_COLOR = "#eab308";
const SYSTEM_LAMBDA_COLOR = "#a78bfa";
// Theme tokens must be passed through the style prop for SVG strokes.
const CURSOR_COLOR = "var(--accent)";
const BASELINE_COLOR = "var(--border)";

export function TimelineSparklineLegend() {
  return (
    <Tooltip
      as="div"
      className="sparkline__legend"
      placement="bottom"
      tip={
        <>
          Each line is normalized independently. Its height shows a relative level,
          not a shared dollar scale.
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

  // Normalize each series independently and leave gaps for missing values.
  const geometry = useMemo(() => {
    if (series.length === 0) {
      return { forecastPath: "", marketPath: "", lambdaPath: "" };
    }

    const innerH = 100;
    const usableH = innerH - PAD_TOP - PAD_BOTTOM;

    const xAt = (i: number) =>
      series.length === 1 ? VIEW_W / 2 : (i / (series.length - 1)) * VIEW_W;

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
