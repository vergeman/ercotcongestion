import { fetchAnalysisNode } from "./client";
import type { AnalysisBasis, AnalysisNodeResponse } from "./types";

// A small LRU cache for the Matrix Read pane's node column (plan/0139-0003) —
// mirrors matrixFrames.ts's cache shape. Keyed by (point, delivery day, hour,
// basis) so the scrubber's rapid re-fetches of an already-visited hour are
// instant, without sharing state with any other consumer of /analysis/node.

const MAX_CACHED = 48;
const cache = new Map<string, AnalysisNodeResponse>();

function cacheKey(point: string, deliveryDate: string, hour: string, basis: AnalysisBasis, runId: string | undefined, mode: "drivers" | "structural"): string {
  return [point, deliveryDate, hour, basis, runId ?? "", mode].join("|");
}

export async function getAnalysisNode(
  point: string,
  deliveryDate: string,
  hour: string,
  basis: AnalysisBasis,
  runId: string | undefined,
  signal?: AbortSignal,
  mode: "drivers" | "structural" = "drivers",
): Promise<AnalysisNodeResponse> {
  const key = cacheKey(point, deliveryDate, hour, basis, runId, mode);
  const cached = cache.get(key);
  if (cached) {
    // Refresh recency on a cache hit — a tiny LRU via Map insertion order.
    cache.delete(key);
    cache.set(key, cached);
    return cached;
  }
  const response = await fetchAnalysisNode(point, { deliveryDate, basis, runId, mode, hours: [hour], signal });
  cache.delete(key);
  cache.set(key, response);
  while (cache.size > MAX_CACHED) {
    const oldest = cache.keys().next().value;
    if (oldest === undefined) break;
    cache.delete(oldest);
  }
  return response;
}
