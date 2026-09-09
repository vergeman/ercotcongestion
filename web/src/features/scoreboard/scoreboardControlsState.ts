import { useReducer } from "react";

export type MetricKey = "topdecile_hit" | "rank_spearman" | "sign_agree";

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

type State = { metric: MetricKey };
export type ScoreboardControlsAction = { type: "metric"; metric: MetricKey };

function reducer(state: State, action: ScoreboardControlsAction): State {
  return { ...state, metric: action.metric };
}

export function useScoreboardControls() {
  return useReducer(reducer, { metric: "rank_spearman" });
}
