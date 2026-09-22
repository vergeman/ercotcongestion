import HeaderNav from "../components/layout/HeaderNav";
import HeaderStatus from "../components/layout/HeaderStatus";
import Tooltip from "../components/ui/Tooltip";
import { useScoreboard } from "../features/scoreboard/useScoreboard";
import { ScoreboardControls } from "../features/scoreboard/ScoreboardControls";
import { METRICS, useScoreboardControls } from "../features/scoreboard/scoreboardControlsState";
import { SERIES, CHART_LABELS } from "../features/scoreboard/seriesMeta";
import { SeriesChart } from "../features/scoreboard/SeriesChart";
import { LiveGradePanel } from "../features/scoreboard/LiveGradePanel";
import { SplitTable } from "../features/scoreboard/SplitTable";
import { Glossary } from "../features/scoreboard/Glossary";
import "../features/scoreboard/scoreboard.css";

// The full backtest scoreboard page
//
// All record spans all time; served daily grades take precedence over weekly fallback.

export default function ScoreboardPage() {
  const [controls, dispatchControls] = useScoreboardControls();
  const {
    weekly, daily, history, backtestLoading, liveLoading, liveError,
    connectionState, lastUpdated,
  } =
    useScoreboard();

  const chartWidth = weekly ? undefined : undefined; // width measured inside chart
  void chartWidth;

  return (
    <div className="sb-page">
      <header className="sb-topbar">
        <HeaderNav active="scoreboard" />
        <HeaderStatus connectionState={connectionState} lastUpdated={lastUpdated} />
      </header>

      <div className="sb-body">
        <main className="sb-main">
          {/* The live half — rendered independently of the backtest board */}
          {daily && (
            <LiveGradePanel
              daily={daily}
            />
          )}
          {!liveLoading && liveError && (
            <div className="sb-empty label">live grades could not be loaded.</div>
          )}

          {backtestLoading && <div className="sb-empty label">loading…</div>}
          {!backtestLoading && !weekly && (
            <div className="sb-empty label">
              no board loaded.
            </div>
          )}

          {weekly && (
            <>
              <ScoreboardControls state={controls} dispatch={dispatchControls} />

              <div className="sb-section-h label">
                Track record · served daily grades with weekly fallback ({METRICS[controls.metric].label})
              </div>
              {history ? (
                <SeriesChart
                  weeklyPoints={history.weekly_points}
                  servedDailyPoints={history.served_daily_points}
                  metric={controls.metric}
                  cutover={weekly.rtc_b_cutover}
                />
              ) : (
                <div className="sb-empty label">track history could not be loaded.</div>
              )}

              {/* legend */}
              <div className="sb-legend">
                {SERIES.map((s) => (
                  <span key={s.seriesId} className="sb-legend__item">
                    <i
                      className="sb-legend__swatch"
                      style={{ background: s.color }}
                    />{" "}
                    {CHART_LABELS[s.seriesId]}
                  </span>
                ))}
              </div>

              <Tooltip
                as="div"
                className="sb-section-h label"
                placement="bottom"
                tip="Each cell is an independent hours-weighted pool. Served daily grades take precedence; weekly grades fill only weeks with no served coverage."
              >
                Track record · pooled pre/post-RTC+B (
                {METRICS[controls.metric].label})
              </Tooltip>
              <div className="sb-section-copy">
                Served grades are authoritative; weekly grades are used when daily grades are unavailable. Results reflect all scored hours; a full week is weighted 7× a day.
              </div>
              <SplitTable weekly={weekly} metric={controls.metric} />
            </>
          )}
        </main>
        <Glossary />
      </div>

    </div>
  );
}
