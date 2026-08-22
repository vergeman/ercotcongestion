import { useEffect, useReducer } from "react";
import { fetchScoreboardSummary } from "../api/scoreboard";
import type { ScoreboardDaily, ScoreboardHeadline, ScoreboardWeekly } from "../api/types";
import type { ConnectionState } from "./useExplorerSession";

type ScoreboardState = {
  weekly: ScoreboardWeekly | null;
  headline: ScoreboardHeadline | null;
  daily: ScoreboardDaily | null;
  loading: boolean;
  connectionState: ConnectionState;
  lastUpdated: Date | null;
};

type Action =
  | { type: "load" }
  | { type: "success"; result: { weekly: ScoreboardWeekly | null; headline: ScoreboardHeadline | null; daily: ScoreboardDaily | null } }
  | { type: "error" };

const initialState: ScoreboardState = {
  weekly: null, headline: null, daily: null, loading: true,
  connectionState: "loading", lastUpdated: null,
};

function reducer(state: ScoreboardState, action: Action): ScoreboardState {
  switch (action.type) {
    case "load": return { ...state, loading: true, connectionState: "loading" };
    case "success": return { ...state, ...action.result, loading: false, connectionState: "ok", lastUpdated: new Date() };
    case "error": return { ...state, loading: false, connectionState: "error" };
  }
}

/** Owns scoreboard server state and cancels superseded summary loads. */
export function useScoreboard(regime: string, horizon: number | null) {
  const [state, dispatch] = useReducer(reducer, initialState);

  useEffect(() => {
    const controller = new AbortController();
    dispatch({ type: "load" });
    fetchScoreboardSummary(regime, horizon, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) dispatch({
          type: "success",
          result: { weekly: result?.weekly ?? null, headline: result?.headline ?? null, daily: result?.daily ?? null },
        });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted && !(error instanceof DOMException && error.name === "AbortError")) dispatch({ type: "error" });
      });
    return () => controller.abort();
  }, [regime, horizon]);

  return state;
}
