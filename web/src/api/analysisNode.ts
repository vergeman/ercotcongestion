import { QueryCache } from "./cache";
import { fetchAnalysisNode } from "./matrix";
import type { AnalysisBasis, AnalysisNodeResponse } from "./types";

// A small LRU cache for the Matrix Read pane's node column (plan/0139-0003) —
// mirrors matrixFrames.ts's cache shape. Keyed by (point, delivery day, hour,
// basis) so the scrubber's rapid re-fetches of an already-visited hour are
// instant, without sharing state with any other consumer of /analysis/node.

const cache = new QueryCache<AnalysisNodeResponse>({ maxSize: 48, ttlMs: 5 * 60 * 1000 });

function cacheKey(
  point: string,
  deliveryDate: string,
  hour: string,
  basis: AnalysisBasis,
  includeDetail: boolean,
): string {
  return [point, deliveryDate, hour, basis, includeDetail].join("|");
}

export async function getAnalysisNode(
  point: string,
  deliveryDate: string,
  hour: string,
  basis: AnalysisBasis,
  signal?: AbortSignal,
  includeDetail = false,
): Promise<AnalysisNodeResponse> {
  const key = cacheKey(point, deliveryDate, hour, basis, includeDetail);
  const cached = cache.get(key);
  if (cached) return cached;
  // Caller-owned cancellation remains caller-owned; the cache only aborts an
  // in-flight request when it is explicitly invalidated or evicted.
  return cache.load(key, () =>
    fetchAnalysisNode(point, {
      deliveryDate,
      basis,
      includeDetail,
      hours: [hour],
      signal,
    }).then((response) => {
      if (!response) throw new Error("analysis/node unavailable");
      return response;
    }),
  );
}

export function clearAnalysisNodeCache(): void { cache.invalidate(); }
