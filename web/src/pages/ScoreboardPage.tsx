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

// The full backtest scoreboard page (plan/0102 §0002, spec-phase3 §5). The board
// the panel's "View full scoreboard" link targets the weekly
// metric-vs-baselines-vs-oracle series, a coverage strip on the shared x-axis,
// and independently hours-weighted pre/post-RTC+B pools. All weeks spans all
// time rather than averaging the two splits; post-RTC+B includes live days.
// independent of the forecast run. Integrity (§6): a model figure never appears
// without persistence + oracle in frame.

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
          {/* The live half — rendered independently of the backtest board, and
          gracefully absent until a served day has been graded (§0004). */}
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
                Track record · weekly backtest and served daily grades ({METRICS[controls.metric].label})
              </div>
              {history ? (
                <SeriesChart
                  points={history.points}
                  metric={controls.metric}
                  cutover={weekly.rtc_b_cutover}
                  boundaryDate={history.boundary_date}
                />
              ) : (
                <div className="sb-empty label">track history could not be loaded.</div>
              )}

              {/* legend — identity for ≥2 series, alongside the direct end-labels */}
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
                tip="Each cell is an independent hours-weighted pool. All weeks spans the full record, not an average of the two RTC+B cells."
              >
                Track record · pooled pre/post-RTC+B (
                {METRICS[controls.metric].label})
              </Tooltip>
              <div className="sb-section-copy">
                Combines hour-weighted historical weekly (w) backtest scores
                with daily (d) forecast grades.
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
