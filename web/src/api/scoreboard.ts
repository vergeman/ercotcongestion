import { requestJson } from "./http";
import type { ScoreboardSummary } from "./types";

export function fetchScoreboardSummary(
  regime = "all",
  horizon?: number | null,
  signal?: AbortSignal,
): Promise<ScoreboardSummary | null> {
  const query = new URLSearchParams({ regime });
  if (horizon != null) query.set("horizon", String(horizon));
  return requestJson("/scoreboard/summary", { query, signal });
}
