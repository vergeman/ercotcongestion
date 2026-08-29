import { useReducer, type Dispatch } from "react";

export type MetricKey =
  | "topdecile_hit"
  | "rank_spearman"
  | "sign_agree";

export const METRICS: Record<MetricKey, {
  label: string;
  fmt: (value: number) => string;
  domain: (values: number[]) => [number, number];
  higher: boolean;
}> = {
  topdecile_hit: { label: "Top-Decile Hit", fmt: (value) => value.toFixed(2), domain: () => [0, 1], higher: true },
  rank_spearman: { label: "Rank ρ", fmt: (value) => value.toFixed(2), domain: () => [0, 1], higher: true },
  sign_agree: { label: "Sign Agreement", fmt: (value) => value.toFixed(2), domain: () => [0, 1], higher: true },
};

const metrics: MetricKey[] = ["rank_spearman", "sign_agree", "topdecile_hit"];

type State = { metric: MetricKey };
type Action = { type: "metric"; metric: MetricKey };

function reducer(state: State, action: Action): State {
  return { ...state, metric: action.metric };
}

export function useScoreboardControls() {
  return useReducer(reducer, { metric: "rank_spearman" });
}

export function ScoreboardControls({ state, dispatch }: {
  state: State;
  dispatch: Dispatch<Action>;
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
