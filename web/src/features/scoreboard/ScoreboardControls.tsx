import { useReducer, type Dispatch } from "react";

export type MetricKey =
  | "topdecile_hit"
  | "rank_spearman"
  | "sign_agree"
  | "pooled_r2"
  | "mae";

export const METRICS: Record<MetricKey, {
  label: string;
  group: "screening" | "magnitude";
  fmt: (value: number) => string;
  domain: (values: number[]) => [number, number];
  higher: boolean;
}> = {
  topdecile_hit: { label: "Top-Decile Hit", group: "screening", fmt: (value) => value.toFixed(2), domain: () => [0, 1], higher: true },
  rank_spearman: { label: "Rank ρ", group: "screening", fmt: (value) => value.toFixed(2), domain: () => [0, 1], higher: true },
  sign_agree: { label: "Sign Agreement", group: "screening", fmt: (value) => value.toFixed(2), domain: () => [0, 1], higher: true },
  pooled_r2: { label: "Pooled R²", group: "magnitude", fmt: (value) => value.toFixed(2), domain: (values) => [Math.min(0, ...values), Math.max(1, ...values)], higher: true },
  mae: { label: "MAE ($/MWh)", group: "magnitude", fmt: (value) => `$${value.toFixed(1)}`, domain: (values) => [0, Math.max(1, ...values) * 1.05], higher: false },
};

const groups: Record<"screening" | "magnitude", MetricKey[]> = {
  screening: ["rank_spearman", "sign_agree", "topdecile_hit"],
  magnitude: ["pooled_r2", "mae"],
};

type State = { group: "screening" | "magnitude"; metric: MetricKey };
type Action = { type: "metric"; metric: MetricKey } | { type: "toggle-group" };

function reducer(state: State, action: Action): State {
  if (action.type === "metric") return { ...state, metric: action.metric };
  const group = state.group === "screening" ? "magnitude" : "screening";
  return { group, metric: groups[group][0] };
}

export function useScoreboardControls() {
  return useReducer(reducer, { group: "screening", metric: "rank_spearman" });
}

export function ScoreboardControls({ state, dispatch }: {
  state: State;
  dispatch: Dispatch<Action>;
}) {
  return (
    <div className="sb-controls">
      <div className="sb-metric-group">
        {groups[state.group].map((metric) => (
          <button
            key={metric}
            className={state.metric === metric ? "active" : ""}
            onClick={() => dispatch({ type: "metric", metric })}
          >
            {METRICS[metric].label}
          </button>
        ))}
      </div>
      <button className="sb-group-toggle" onClick={() => dispatch({ type: "toggle-group" })}>
        {state.group === "screening" ? "Show magnitude (R²/MAE) →" : "← Back to screening"}
      </button>
    </div>
  );
}
