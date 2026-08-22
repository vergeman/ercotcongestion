import { requestJson } from "./http";
import { QueryCache } from "./cache";
import type {
  ScoreboardDaily,
  ScoreboardHeadline,
  ScoreboardSummary,
  ScoreboardWeekly,
} from "./types";

const weeklyCache = new QueryCache<ScoreboardWeekly | null>({ maxSize: 12, ttlMs: 60_000 });
const headlineCache = new QueryCache<ScoreboardHeadline | null>({ maxSize: 12, ttlMs: 60_000 });
const dailyCache = new QueryCache<ScoreboardDaily | null>({ maxSize: 4, ttlMs: 60_000 });

export function fetchScoreboardSummary(
  regime = "all",
  horizon?: number | null,
  signal?: AbortSignal,
): Promise<ScoreboardSummary | null> {
  const query = new URLSearchParams({ regime });
  if (horizon != null) query.set("horizon", String(horizon));
  return requestJson("/scoreboard/summary", { query, signal });
}

export function fetchScoreboardWeekly(
  regime = "all",
  _signal?: AbortSignal,
): Promise<ScoreboardWeekly | null> {
  return weeklyCache.load(regime, (signal) => requestJson("/scoreboard/weekly", {
    query: new URLSearchParams({ regime }), signal,
  }));
}

export function fetchScoreboardHeadline(
  regime = "all",
  _signal?: AbortSignal,
): Promise<ScoreboardHeadline | null> {
  return headlineCache.load(regime, (signal) => requestJson("/scoreboard/headline", {
    query: new URLSearchParams({ regime }), signal,
  }));
}

export function fetchScoreboardDaily(
  horizon?: number | null,
  _signal?: AbortSignal,
): Promise<ScoreboardDaily | null> {
  const query = new URLSearchParams();
  if (horizon != null) query.set("horizon", String(horizon));
  return dailyCache.load(query.toString(), (signal) => requestJson("/scoreboard/daily", { query, signal }));
}
