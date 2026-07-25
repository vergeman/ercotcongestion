import { fetchMatrixFrame, type MatrixFrameRequest } from "./client";
import type { MatrixFrame } from "./types";

const MAX_CACHED_FRAMES = 36;

export interface MatrixFrameBounds {
  rowLimit?: number;
  columnLimit?: number;
  columnSet?: "core";
}

interface CachedFrame {
  frame: MatrixFrame;
  cacheKey: string;
}

// The request index is intentionally distinct from the frame cache.  A frame's
// resolved run and delivery day are only known after the API responds, while
// playback asks for a timestamp.  Keeping both lets us preserve those causal
// identifiers in the bounded cache key without leaking dense frames into the
// nodal playback cache.
const requestIndex = new Map<string, string>();
const frames = new Map<string, CachedFrame>();

function normalizedBounds(bounds: MatrixFrameBounds = {}) {
  return {
    rowLimit: bounds.rowLimit ?? 30,
    columnLimit: bounds.columnLimit ?? 40,
    columnSet: bounds.columnSet ?? "core",
  } as const;
}

function requestKey(intervalTs: Date, bounds: MatrixFrameBounds = {}): string {
  const normalized = normalizedBounds(bounds);
  return [
    intervalTs.toISOString(),
    normalized.rowLimit,
    normalized.columnSet,
    normalized.columnLimit,
  ].join("|");
}

export function matrixFrameCacheKey(
  frame: Pick<MatrixFrame, "run_id" | "delivery_date" | "interval_ts">,
  bounds: MatrixFrameBounds = {}
): string {
  const normalized = normalizedBounds(bounds);
  return [
    frame.run_id,
    frame.delivery_date,
    frame.interval_ts,
    normalized.rowLimit,
    normalized.columnSet,
    normalized.columnLimit,
  ].join("|");
}

function remember(request: string, frame: MatrixFrame, bounds: MatrixFrameBounds): MatrixFrame {
  const key = matrixFrameCacheKey(frame, bounds);
  // Refresh recency on both cache hits and a newly fetched frame.
  frames.delete(key);
  frames.set(key, { frame, cacheKey: key });
  requestIndex.delete(request);
  requestIndex.set(request, key);

  while (frames.size > MAX_CACHED_FRAMES) {
    const oldest = frames.keys().next().value;
    if (oldest === undefined) break;
    frames.delete(oldest);
    for (const [indexedRequest, indexedKey] of requestIndex) {
      if (indexedKey === oldest) requestIndex.delete(indexedRequest);
    }
  }
  return frame;
}

/** Read or load a Matrix frame without sharing the nodal playback cache. */
export async function getMatrixFrame(
  intervalTs: Date,
  bounds: MatrixFrameBounds = {},
  signal?: AbortSignal
): Promise<MatrixFrame> {
  const request = requestKey(intervalTs, bounds);
  const cachedKey = requestIndex.get(request);
  const cached = cachedKey ? frames.get(cachedKey) : undefined;
  if (cached) {
    // A Map's insertion order gives us a tiny LRU cache with no extra state.
    frames.delete(cached.cacheKey);
    frames.set(cached.cacheKey, cached);
    return cached.frame;
  }

  const requestOptions: MatrixFrameRequest = { ...normalizedBounds(bounds), signal };
  const frame = await fetchMatrixFrame(intervalTs, requestOptions);
  return remember(request, frame, bounds);
}

export function clearMatrixFrameCache(): void {
  requestIndex.clear();
  frames.clear();
}
