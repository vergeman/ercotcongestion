import { useEffect, useMemo, useRef } from "react";
import type { ScoreHistoryPoint } from "../../api/types";
import { METRICS, type MetricKey } from "./scoreboardControlsState";
import { useScoreboardChart } from "./useScoreboardChart";
import { SERIES, CHART_LABELS } from "./seriesMeta";
import { fmtWeek, fmtDay } from "./format";

type Cadence = "weekly" | "daily";

const dayMs = (day: string) => Date.parse(`${day}T00:00:00Z`);
const FOCUS_DAYS = 28;
const DAY_MS = 86_400_000;
const M = { t: 14, r: 116, b: 22, l: 42 };
const H = 280;

// One scrollable chart with fixed spacing for each calendar day.
export function SeriesChart({
  weeklyPoints,
  servedDailyPoints,
  metric,
  cutover,
}: {
  weeklyPoints: ScoreHistoryPoint[];
  servedDailyPoints: ScoreHistoryPoint[];
  metric: MetricKey;
  cutover: string;
}) {
  const dates = useMemo(
    () =>
      Array.from(
        new Set([
          ...weeklyPoints.map((point) => point.week),
          ...servedDailyPoints.map((point) => point.delivery_date),
        ].filter((date): date is string => date != null))
      ).sort(),
    [weeklyPoints, servedDailyPoints]
  );
  const byCadence = useMemo(() => {
    const index = (points: ScoreHistoryPoint[], cadence: Cadence) => {
      const values = new Map<string, ScoreHistoryPoint>();
      for (const point of points) {
        const date = cadence === "weekly" ? point.week : point.delivery_date;
        if (date != null) values.set(`${date}|${point.series_id}`, point);
      }
      return values;
    };

    return {
      weekly: index(weeklyPoints, "weekly"),
      daily: index(servedDailyPoints, "daily"),
    };
  }, [weeklyPoints, servedDailyPoints]);

  const meta = METRICS[metric];
  const seriesVals = useMemo(() => {
    const valuesAt = (cadence: Cadence, seriesId: string) =>
      dates.map((date) => {
        const point = byCadence[cadence].get(`${date}|${seriesId}`);
        const value = point ? (point[metric] as number | null) : null;
        return value == null ? null : value;
      });

    return SERIES.map((series) => ({
      ...series,
      weekly: valuesAt("weekly", series.seriesId),
      daily: valuesAt("daily", series.seriesId),
    }));
  }, [dates, byCadence, metric]);
  const allVals = seriesVals.flatMap((series) =>
    [...series.weekly, ...series.daily].filter(
      (value): value is number => value != null
    )
  );
  const [dMin, dMax] = meta.domain(allVals);

  const n = dates.length;
  const { wrapRef, width, hover, clearHover, moveHover, setHoverIndex } =
    useScoreboardChart(n);
  const firstMs = dates.length ? dayMs(dates[0]) : 0;
  const lastMs = dates.length ? dayMs(dates[dates.length - 1]) : firstMs;
  const dayWidth = Math.max(18, (width - 32 - M.l - M.r) / FOCUS_DAYS);
  const chartWidth = Math.max(
    width - 32,
    M.l + M.r + ((lastMs - firstMs) / DAY_MS) * dayWidth
  );
  const plotW = Math.max(1, chartWidth - M.l - M.r);
  const plotH = H - M.t - M.b;
  const x = (date: string) =>
    M.l + ((dayMs(date) - firstMs) / DAY_MS) * dayWidth;
  const y = (value: number) =>
    M.t +
    (dMax === dMin ? plotH / 2 : (1 - (value - dMin) / (dMax - dMin)) * plotH);

  const linePath = (values: (number | null)[]) => {
    let path = "";
    let pen = false;
    values.forEach((value, i) => {
      if (value == null) {
        pen = false;
        return;
      }
      path += `${pen ? "L" : "M"}${x(dates[i]).toFixed(1)} ${y(value).toFixed(1)} `;
      pen = true;
    });
    return path.trim();
  };
  const transitionPath = (weekly: (number | null)[], daily: (number | null)[]) => {
    const lastWeekly = weekly.findLastIndex((value) => value != null);
    const firstDaily = daily.findIndex((value) => value != null);
    if (lastWeekly < 0 || firstDaily < 0) return "";
    return (
      `M${x(dates[lastWeekly]).toFixed(1)} ${y(weekly[lastWeekly]!).toFixed(1)} ` +
      `L${x(dates[firstDaily]).toFixed(1)} ${y(daily[firstDaily]!).toFixed(1)}`
    );
  };

  type EndLabel = { color: string; label: string; y: number };
  const endLabels: EndLabel[] = [];
  for (const series of seriesVals) {
    for (let i = dates.length - 1; i >= 0; i--) {
      const value = series.daily[i] ?? series.weekly[i];
      if (value != null) {
        endLabels.push({
          color: series.color,
          label: CHART_LABELS[series.seriesId],
          y: y(value),
        });
        break;
      }
    }
  }
  endLabels.sort((a, b) => a.y - b.y);
  for (let i = 1; i < endLabels.length; i++) {
    if (endLabels[i].y - endLabels[i - 1].y < 12) {
      endLabels[i].y = endLabels[i - 1].y + 12;
    }
  }

  const closestDateIndex = (targetMs: number) =>
    dates.reduce(
      (closest, date, index) =>
        Math.abs(dayMs(date) - targetMs) < Math.abs(dayMs(dates[closest]) - targetMs)
          ? index
          : closest,
      0
    );
  const cutIdx = dates.findIndex((date) => date >= cutover);
  const firstServedDate = servedDailyPoints
    .map((point) => point.delivery_date)
    .filter((date): date is string => date != null)
    .sort()[0];
  const tickIdx = dates.reduce<number[]>((ticks, date, index) => {
    const interval = firstServedDate != null && date >= firstServedDate ? 7 : 28;
    const previous = ticks.length ? dates[ticks[ticks.length - 1]] : null;
    if (previous == null || dayMs(date) - dayMs(previous) >= interval * DAY_MS) {
      ticks.push(index);
    }
    return ticks;
  }, []);
  if (n > 1 && tickIdx[tickIdx.length - 1] !== n - 1) tickIdx.push(n - 1);
  const zeroInDomain = dMin < 0 && dMax > 0;
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const element = scrollRef.current;
    if (element) element.scrollLeft = element.scrollWidth;
  }, [chartWidth, firstMs, lastMs]);

  const onMove = (event: React.MouseEvent<SVGRectElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const targetMs =
      firstMs + ((event.clientX - rect.left - M.l) / dayWidth) * DAY_MS;
    setHoverIndex(closestDateIndex(targetMs));
  };

  return (
    <div ref={wrapRef} className="sb-chart">
      <div ref={scrollRef} className="sb-chart__scroll">
        <div className="sb-chart__canvas" style={{ width: chartWidth }}>
          <svg
            width={chartWidth}
            height={H}
            role="img"
            aria-label={`${meta.label} over time`}
          >
            {[dMin, (dMin + dMax) / 2, dMax].map((value, key) => (
              <g key={key}>
                <line
                  x1={M.l}
                  x2={M.l + plotW}
                  y1={y(value)}
                  y2={y(value)}
                  stroke="var(--border)"
                  strokeWidth={1}
                />
                <text
                  x={M.l - 6}
                  y={y(value) + 3}
                  textAnchor="end"
                  className="sb-axis"
                >
                  {meta.fmt(value)}
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

            {tickIdx.map((index) => (
              <text
                key={index}
                x={x(dates[index])}
                y={H - 6}
                textAnchor="middle"
                className="sb-axis"
              >
                {fmtWeek(dates[index])}
              </text>
            ))}

            {cutIdx > 0 && (
              <g>
                <line
                  x1={x(dates[cutIdx])}
                  x2={x(dates[cutIdx])}
                  y1={M.t}
                  y2={M.t + plotH}
                  stroke="var(--text-secondary)"
                  strokeWidth={1}
                  strokeDasharray="3 3"
                />
                <text
                  x={x(dates[cutIdx]) + 3}
                  y={M.t + 9}
                  className="sb-axis sb-axis--mark"
                >
                  RTC+B
                </text>
              </g>
            )}
            {firstServedDate != null && (
              <g>
                <line
                  x1={x(firstServedDate)}
                  x2={x(firstServedDate)}
                  y1={M.t}
                  y2={M.t + plotH}
                  stroke="var(--accent)"
                  strokeWidth={1}
                  strokeDasharray="5 3"
                />
                <text
                  x={x(firstServedDate) + 3}
                  y={M.t + 21}
                  className="sb-axis sb-axis--mark"
                >
                  Served grades
                </text>
              </g>
            )}

            {seriesVals.flatMap((series) =>
              (["weekly", "daily"] as Cadence[]).map((cadence) => (
                <path
                  key={`${series.seriesId}-${cadence}`}
                  d={linePath(series[cadence])}
                  fill="none"
                  stroke={series.color}
                  strokeWidth={2}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  strokeDasharray={cadence === "daily" ? "4 2" : undefined}
                />
              ))
            )}
            {seriesVals.map((series) => (
              <path
                key={`${series.seriesId}-transition`}
                d={transitionPath(series.weekly, series.daily)}
                fill="none"
                stroke={series.color}
                strokeWidth={2}
                strokeLinecap="round"
                strokeDasharray="2 4"
                opacity={0.7}
              />
            ))}

            {endLabels.map((label, key) => (
              <text
                key={key}
                x={M.l + plotW + 5}
                y={label.y + 3}
                className="sb-endlabel"
                fill={label.color}
              >
                {label.label}
              </text>
            ))}

            {hover != null && (
              <g>
                <line
                  x1={x(dates[hover])}
                  x2={x(dates[hover])}
                  y1={M.t}
                  y2={M.t + plotH}
                  stroke="var(--border-bright)"
                  strokeWidth={1}
                />
                {seriesVals.flatMap((series) =>
                  (["weekly", "daily"] as Cadence[]).map((cadence) => {
                    const value = series[cadence][hover];
                    return value == null ? null : (
                      <circle
                        key={`${series.seriesId}-${cadence}`}
                        cx={x(dates[hover])}
                        cy={y(value)}
                        r={3.5}
                        fill={series.color}
                        stroke="var(--bg-panel)"
                        strokeWidth={1.5}
                      />
                    );
                  })
                )}
              </g>
            )}

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
              aria-label="Use left and right arrow keys to inspect Scoreboard values"
            />
          </svg>

          {hover != null && (
            <div
              className="sb-tip"
              style={{
                left: Math.min(x(dates[hover]) + 8, chartWidth - 140),
                top: M.t,
              }}
            >
              {(["weekly", "daily"] as Cadence[]).map((cadence) => {
                const values = seriesVals.map((series) => series[cadence]);
                if (values.every((value) => value[hover] == null)) return null;

                return (
                  <div key={cadence}>
                    <div className="sb-tip__wk">
                      {cadence === "daily"
                        ? `Served daily grade · ${fmtDay(dates[hover])}`
                        : `Walk-forward backtest week · ${fmtWeek(dates[hover])}`}
                    </div>
                    {SERIES.map((series, index) => (
                      <div key={series.seriesId} className="sb-tip__row">
                        <span
                          className="sb-tip__dot"
                          style={{ background: series.color }}
                        />
                        <span className="sb-tip__lbl">
                          {CHART_LABELS[series.seriesId]}
                        </span>
                        <span className="sb-tip__val">
                          {values[index][hover] == null
                            ? "—"
                            : meta.fmt(values[index][hover]!)}
                        </span>
                      </div>
                    ))}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
