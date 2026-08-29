import { requestJson } from "./http";
import { QueryCache } from "./cache";
import type {
  ScoreboardSummary,
} from "./types";

const summaryCache = new QueryCache<ScoreboardSummary | null>({ maxSize: 4, ttlMs: 60_000 });

export function fetchScoreboardSummary(): Promise<ScoreboardSummary | null> {
  return summaryCache.load("", (signal) => requestJson("/scoreboard/summary", { signal }));
}
