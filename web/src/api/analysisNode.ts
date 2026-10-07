import { QueryCache } from "./cache";
import { ApiError } from "./http";
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

export function getCachedAnalysisNode(
  point: string,
  deliveryDate: string,
  hour: string,
  basis: AnalysisBasis,
  includeDetail = false,
): AnalysisNodeResponse | undefined {
  return cache.get(cacheKey(point, deliveryDate, hour, basis, includeDetail));
}

export async function getAnalysisNode(
  point: string,
  deliveryDate: string,
  hour: string,
  basis: AnalysisBasis,
  signal?: AbortSignal,
  includeDetail = false,
): Promise<AnalysisNodeResponse> {
  if (signal?.aborted) throw new ApiError("/analysis/node request aborted", "abort");
  const key = cacheKey(point, deliveryDate, hour, basis, includeDetail);
  const cached = cache.get(key);
  if (cached) return cached;
  // Caller-owned cancellation remains caller-owned; the cache only aborts an
  // in-flight request when it is explicitly invalidated or evicted.
  const response = await cache.load(key, (cacheSignal) =>
    fetchAnalysisNode(point, {
      deliveryDate,
      basis,
      includeDetail,
      hours: [hour],
      signal: cacheSignal,
    }).then((response) => {
      if (!response) throw new Error("analysis/node unavailable");
      return response;
    }),
  );
  if (signal?.aborted) throw new ApiError("/analysis/node request aborted", "abort");
  return response;
}
