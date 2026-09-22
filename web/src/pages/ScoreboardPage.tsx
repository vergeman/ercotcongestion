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
// All weeks spans all time rather than averaging the two splits; post-RTC+B includes live days.
// independent of the forecast run.

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
                Track record · walk-forward weekly and served daily grades ({METRICS[controls.metric].label})
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
                tip="Each cell is an independent hours-weighted pool. Post-RTC+B includes final served grades; All weeks spans the full record."
              >
                Track record · pooled pre/post-RTC+B (
                {METRICS[controls.metric].label})
              </Tooltip>
              <div className="sb-section-copy">
                The chart uses separate weekly and served-daily paths on one time scale; pooled cells combine them by scored hours.
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
