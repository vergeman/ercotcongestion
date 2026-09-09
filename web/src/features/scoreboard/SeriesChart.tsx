import { useMemo } from "react";
import type { ScoreHistoryPoint } from "../../api/types";
import { METRICS, type MetricKey } from "./ScoreboardControls";
import { useScoreboardChart } from "./useScoreboardChart";
import { SERIES, CHART_LABELS } from "./seriesMeta";
import { fmtWeek, fmtDay } from "./format";

// The backtest + served-grade series chart (hand-rolled SVG).
export function SeriesChart({
  points,
  metric,
  cutover,
  boundaryDate,
}: {
  points: ScoreHistoryPoint[];
  metric: MetricKey;
  cutover: string;
  boundaryDate: string | null;
}) {
  const dates = useMemo(
    () => Array.from(new Set(points.map((p) => p.week ?? p.delivery_date ?? ""))).sort(),
    [points]
  );
  const byKey = useMemo(() => {
    const m = new Map<string, ScoreHistoryPoint>();
    for (const p of points) m.set(`${p.week ?? p.delivery_date}|${p.series_id}`, p);
    return m;
  }, [points]);

  const meta = METRICS[metric];
  const valueAt = (i: number, seriesId: string): number | null => {
    const p = byKey.get(`${dates[i]}|${seriesId}`);
    const v = p ? (p[metric] as number | null) : null;
    return v == null ? null : v;
  };

  const seriesVals = useMemo(
    () =>
      SERIES.map((s) => ({
        ...s,
        vals: dates.map((_, i) => valueAt(i, s.seriesId)),
      })),
    [dates, byKey, metric] // eslint-disable-line react-hooks/exhaustive-deps
  );

  const allVals = seriesVals.flatMap((s) =>
    s.vals.filter((v): v is number => v != null)
  );
  const [dMin, dMax] = meta.domain(allVals);

  // Right margin holds the direct end-labels (Persistence / Climatology ≈ 80px
  // at the 11px label face) — keep it wide enough that they don't clip.
  const M = { t: 14, r: 116, b: 22, l: 42 };
  const H = 280;
  const n = dates.length;
  const {
    wrapRef, width, hover, clearHover, moveHover, setHoverFromCoordinate,
  } = useScoreboardChart(n);
  const plotW = Math.max(1, width - M.l - M.r);
  const plotH = H - M.t - M.b;

  const x = (i: number) => M.l + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const y = (v: number) =>
    M.t +
    (dMax === dMin ? plotH / 2 : (1 - (v - dMin) / (dMax - dMin)) * plotH);

  const linePath = (vals: (number | null)[]): string => {
    let d = "";
    let pen = false;
    vals.forEach((v, i) => {
      if (v == null) {
        pen = false;
        return;
      }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)} `;
      pen = true;
    });
    return d.trim();
  };

  // last non-null point per series → the direct end-label (identity, not
  // color-alone), with a small vertical de-collision.
  type EndLabel = { color: string; label: string; y: number };
  const endLabels: EndLabel[] = [];
  for (const s of seriesVals) {
    for (let i = s.vals.length - 1; i >= 0; i--) {
      const v = s.vals[i];
      if (v != null) {
        endLabels.push({ color: s.color, label: CHART_LABELS[s.seriesId], y: y(v) });
        break;
      }
    }
  }
  endLabels.sort((a, b) => a.y - b.y);
  for (let i = 1; i < endLabels.length; i++) {
    if (endLabels[i].y - endLabels[i - 1].y < 12)
      endLabels[i].y = endLabels[i - 1].y + 12;
  }

  const cutIdx = dates.findIndex((d) => d >= cutover);
  const boundaryIdx = boundaryDate == null ? -1 : dates.findIndex((d) => d >= boundaryDate);
  const zeroInDomain = dMin < 0 && dMax > 0;

  // x tick indices: a handful across the span.
  const tickIdx =
    n <= 1
      ? [0]
      : [
          0,
          Math.floor(n / 4),
          Math.floor(n / 2),
          Math.floor((3 * n) / 4),
          n - 1,
        ];

  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    setHoverFromCoordinate(mx, plotW);
  };

  return (
    <div ref={wrapRef} className="sb-chart" style={{ position: "relative" }}>
      <svg
        width={width}
        height={H}
        role="img"
        aria-label={`${meta.label} by week`}
      >
        {/* y gridlines + labels */}
        {[dMin, (dMin + dMax) / 2, dMax].map((v, k) => (
          <g key={k}>
            <line
              x1={M.l}
              x2={M.l + plotW}
              y1={y(v)}
              y2={y(v)}
              stroke="var(--border)"
              strokeWidth={1}
            />
            <text x={M.l - 6} y={y(v) + 3} textAnchor="end" className="sb-axis">
              {meta.fmt(v)}
            </text>
          </g>
        ))}
        {zeroInDomain && (
          <line
            x1={M.l}
            x2={M.l + plotW}
            y1={y(0)}
            y2={y(0)}
            stroke="var(--text-muted)"
            strokeWidth={1}
            strokeDasharray="2 2"
          />
        )}

        {/* x ticks */}
        {tickIdx.map((i) => (
          <text
            key={i}
            x={x(i)}
            y={H - 6}
            textAnchor="middle"
            className="sb-axis"
          >
            {fmtWeek(dates[i])}
          </text>
        ))}

        {/* RTC+B cutover marker */}
        {cutIdx > 0 && (
          <g>
            <line
              x1={x(cutIdx)}
              x2={x(cutIdx)}
              y1={M.t}
              y2={M.t + plotH}
              stroke="var(--text-secondary)"
              strokeWidth={1}
              strokeDasharray="3 3"
            />
            <text
              x={x(cutIdx) + 3}
              y={M.t + 9}
              className="sb-axis sb-axis--mark"
            >
              RTC+B
            </text>
          </g>
        )}

        {boundaryIdx > 0 && (
          <g>
            <line
              x1={x(boundaryIdx)}
              x2={x(boundaryIdx)}
              y1={M.t}
              y2={M.t + plotH}
              stroke="var(--accent)"
              strokeWidth={1}
              strokeDasharray="5 3"
            />
            <text x={x(boundaryIdx) + 3} y={M.t + 21} className="sb-axis sb-axis--mark">
              Served grades
            </text>
          </g>
        )}

        {/* series lines */}
        {seriesVals.map((s) => (
          <path
            key={s.seriesId}
            d={linePath(s.vals)}
            fill="none"
            stroke={s.color}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}

        {/* direct end-labels (secondary encoding for the CVD floor) */}
        {endLabels.map((e, k) => (
          <text
            key={k}
            x={M.l + plotW + 5}
            y={e.y + 3}
            className="sb-endlabel"
            fill={e.color}
          >
            {e.label}
          </text>
        ))}

        {/* hover guide + markers */}
        {hover != null && (
          <g>
            <line
              x1={x(hover)}
              x2={x(hover)}
              y1={M.t}
              y2={M.t + plotH}
              stroke="var(--border-bright)"
              strokeWidth={1}
            />
            {seriesVals.map((s) => {
              const v = s.vals[hover];
              return v == null ? null : (
                <circle
                  key={s.seriesId}
                  cx={x(hover)}
                  cy={y(v)}
                  r={3.5}
                  fill={s.color}
                  stroke="var(--bg-panel)"
                  strokeWidth={1.5}
                />
              );
            })}
          </g>
        )}

        {/* hover capture */}
        <rect
          x={M.l}
          y={M.t}
          width={plotW}
          height={plotH}
          fill="transparent"
          onMouseMove={onMove}
          onMouseLeave={clearHover}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft") moveHover(-1);
            if (event.key === "ArrowRight") moveHover(1);
          }}
          tabIndex={0}
          aria-label="Use left and right arrow keys to inspect backtest and served-grade values"
        />
      </svg>

      {hover != null && (
        <div
          className="sb-tip"
          style={{ left: Math.min(x(hover) + 8, width - 140), top: M.t }}
        >
          <div className="sb-tip__wk">
            {points.find((p) => (p.week ?? p.delivery_date) === dates[hover])?.cadence === "served_daily"
              ? `Served daily grade · ${fmtDay(dates[hover])}`
              : `Walk-forward backtest week · ${fmtWeek(dates[hover])}`}
          </div>
          {seriesVals.map((s) => {
            const v = s.vals[hover];
            return (
              <div key={s.seriesId} className="sb-tip__row">
                <span className="sb-tip__dot" style={{ background: s.color }} />
                <span className="sb-tip__lbl">{CHART_LABELS[s.seriesId]}</span>
                <span className="sb-tip__val">
                  {v == null ? "—" : meta.fmt(v)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
