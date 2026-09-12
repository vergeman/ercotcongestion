import type { Dispatch } from "react";
import { METRICS, type MetricKey, type ScoreboardControlsAction } from "./scoreboardControlsState";

const metrics: MetricKey[] = ["rank_spearman", "sign_agree", "topdecile_hit"];

type State = { metric: MetricKey };

export function ScoreboardControls({ state, dispatch }: {
  state: State;
  dispatch: Dispatch<ScoreboardControlsAction>;
}) {
  return (
    <div className="sb-controls">
      <div className="sb-metric-group">
        {metrics.map((metric) => (
          <button
            key={metric}
            className={state.metric === metric ? "active" : ""}
            onClick={() => dispatch({ type: "metric", metric })}
          >
            {METRICS[metric].label}
          </button>
        ))}
      </div>
    </div>
  );
}
