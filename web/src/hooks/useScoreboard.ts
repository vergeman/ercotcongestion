import { useEffect, useMemo, useReducer } from "react";
import {
  fetchScoreboardDaily,
  fetchScoreboardHeadline,
  fetchScoreboardWeekly,
} from "../api/scoreboard";
import type { ScoreboardDaily, ScoreboardHeadline, ScoreboardWeekly } from "../api/types";
import type { ConnectionState } from "./useExplorerSession";

type ScoreboardState = {
  weekly: ScoreboardWeekly | null;
  headline: ScoreboardHeadline | null;
  daily: ScoreboardDaily | null;
  backtestLoading: boolean;
  liveLoading: boolean;
  backtestError: boolean;
  liveError: boolean;
  connectionState: ConnectionState;
  lastUpdated: Date | null;
};

type Action = { type: "patch"; patch: Partial<ScoreboardState> };

const initialState: ScoreboardState = {
  weekly: null, headline: null, daily: null,
  backtestLoading: true, liveLoading: true, backtestError: false, liveError: false,
  connectionState: "loading", lastUpdated: null,
};

function reducer(state: ScoreboardState, action: Action): ScoreboardState {
  return { ...state, ...action.patch };
}

const isAbort = (error: unknown) =>
  error instanceof DOMException && error.name === "AbortError";

/** Owns independently cached live-grade and backtest resources. */
export function useScoreboard(horizon: number | null) {
  const [state, dispatch] = useReducer(reducer, initialState);

  useEffect(() => {
    const controller = new AbortController();
    dispatch({ type: "patch", patch: { backtestLoading: true, backtestError: false } });
    Promise.all([
      fetchScoreboardWeekly(),
      fetchScoreboardHeadline(),
    ])
      .then(([weekly, headline]) => {
        if (!controller.signal.aborted) {
          dispatch({
            type: "patch",
            patch: { weekly, headline, backtestLoading: false, lastUpdated: new Date() },
          });
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted && !isAbort(error)) {
          dispatch({ type: "patch", patch: { weekly: null, headline: null, backtestLoading: false, backtestError: true } });
        }
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    dispatch({ type: "patch", patch: { liveLoading: true, liveError: false } });
    fetchScoreboardDaily(horizon)
      .then((daily) => {
        if (!controller.signal.aborted) {
          dispatch({ type: "patch", patch: { daily, liveLoading: false, lastUpdated: new Date() } });
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted && !isAbort(error)) {
          dispatch({ type: "patch", patch: { daily: null, liveLoading: false, liveError: true } });
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
