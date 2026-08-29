import { requestJson } from "./http";
import { QueryCache } from "./cache";
import type {
  ScoreboardSummary,
} from "./types";

const summaryCache = new QueryCache<ScoreboardSummary | null>({ maxSize: 4, ttlMs: 60_000 });

export function fetchScoreboardSummary(
  horizon?: number | null,
): Promise<ScoreboardSummary | null> {
  const query = new URLSearchParams();
  if (horizon != null) query.set("horizon", String(horizon));
  return summaryCache.load(query.toString(), (signal) => requestJson("/scoreboard/summary", { query, signal }));
}
