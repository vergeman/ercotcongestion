import { useEffect, useMemo, useReducer } from "react";
import { fetchScoreboardSummary } from "../api/scoreboard";
import type { ScoreboardDaily, ScoreboardHeadline, ScoreboardHistory, ScoreboardWeekly } from "../api/types";
import type { ConnectionState } from "./useExplorerSession";

type ScoreboardState = {
  weekly: ScoreboardWeekly | null;
  headline: ScoreboardHeadline | null;
  daily: ScoreboardDaily | null;
  history: ScoreboardHistory | null;
  backtestLoading: boolean;
  liveLoading: boolean;
  backtestError: boolean;
  liveError: boolean;
  connectionState: ConnectionState;
  lastUpdated: Date | null;
};

type Action = { type: "patch"; patch: Partial<ScoreboardState> };

const initialState: ScoreboardState = {
  weekly: null, headline: null, daily: null, history: null,
  backtestLoading: true, liveLoading: true, backtestError: false, liveError: false,
  connectionState: "loading", lastUpdated: null,
};

function reducer(state: ScoreboardState, action: Action): ScoreboardState {
  return { ...state, ...action.patch };
}

const isAbort = (error: unknown) =>
  error instanceof DOMException && error.name === "AbortError";

/** Owns the Scoreboard's single bundled response. */
export function useScoreboard(horizon: number | null) {
  const [state, dispatch] = useReducer(reducer, initialState);

  useEffect(() => {
    const controller = new AbortController();
    dispatch({ type: "patch", patch: {
      backtestLoading: true, liveLoading: true, backtestError: false, liveError: false,
    } });
    fetchScoreboardSummary(horizon)
      .then((summary) => {
        if (!controller.signal.aborted) {
          dispatch({
            type: "patch",
            patch: {
              weekly: summary?.weekly ?? null,
              headline: summary?.headline ?? null,
              daily: summary?.daily ?? null,
              history: summary?.history ?? null,
              backtestLoading: false,
              liveLoading: false,
              lastUpdated: new Date(),
            },
          });
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted && !isAbort(error)) {
          dispatch({ type: "patch", patch: {
            weekly: null, headline: null, daily: null, history: null,
            backtestLoading: false, liveLoading: false, backtestError: true, liveError: true,
          } });
        }
      });
    return () => controller.abort();
  }, [horizon]);

  return useMemo(() => {
    const loading = state.backtestLoading || state.liveLoading;
    const connectionState: ConnectionState = loading
      ? "loading"
      : state.backtestError && state.liveError
        ? "error"
        : "ok";
    return { ...state, loading, connectionState };
  }, [state]);
}
