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
                Walk-forward weekly backtest ({METRICS[controls.metric].label})
              </div>
              {history ? (
                <SeriesChart
                  points={history.weekly_points}
                  metric={controls.metric}
                  cadence="weekly"
                  cutover={weekly.rtc_b_cutover}
                />
              ) : (
                <div className="sb-empty label">weekly history could not be loaded.</div>
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

              <div className="sb-section-h label">
                Final served daily grades ({METRICS[controls.metric].label})
              </div>
              {history?.served_daily_points.length ? (
                <SeriesChart
                  points={history.served_daily_points}
                  metric={controls.metric}
                  cadence="daily"
                />
              ) : (
                <div className="sb-section-copy">no final served grades available.</div>
              )}

              <Tooltip
                as="div"
                className="sb-section-h label"
                placement="bottom"
                tip="Each cell is an independent hours-weighted weekly pool. All weeks spans the full record, not an average of the two RTC+B cells."
              >
                Track record · pooled pre/post-RTC+B (
                {METRICS[controls.metric].label})
              </Tooltip>
              <div className="sb-section-copy">
                Weekly walk-forward scores are pooled separately from final served-daily grades.
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
