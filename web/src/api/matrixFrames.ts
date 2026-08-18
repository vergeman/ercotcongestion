import { fetchMatrixFrame, type MatrixFrameRequest } from "./client";
import type { MatrixFrame } from "./types";

const MAX_CACHED_FRAMES = 36;

export interface MatrixFrameBounds {
  rowLimit?: number;
  columnLimit?: number;
  rowPreset?: "top30" | "top100" | "pinned";
  constraintType?: "gtc" | "transmission" | "radial";
  constraintSearch?: string;
  settlementPointSearch?: string;
  pinnedConstraints?: string[];
  pinnedSettlementPoints?: string[];
  columnSet?: "core" | "anchors" | "pinned" | "core_pinned" | "default_anchors";
  orientation?: "constraints" | "nodes";
  rowOrder?: "contribution" | "cursor_mu" | "anchor_contribution";
  peekConstraint?: string | null;
  peekSettlementPoint?: string | null;
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
    rowPreset: bounds.rowPreset ?? "top30",
    constraintType: bounds.constraintType ?? "",
    constraintSearch: bounds.constraintSearch ?? "",
    settlementPointSearch: bounds.settlementPointSearch ?? "",
    pinnedConstraints: bounds.pinnedConstraints ?? [],
    pinnedSettlementPoints: bounds.pinnedSettlementPoints ?? [],
    columnSet: bounds.columnSet ?? "core",
    orientation: bounds.orientation ?? "constraints",
    rowOrder: bounds.rowOrder ?? "contribution",
    peekConstraint: bounds.peekConstraint ?? "",
    peekSettlementPoint: bounds.peekSettlementPoint ?? "",
  } as const;
}

function requestKey(intervalTs: Date, bounds: MatrixFrameBounds = {}): string {
  const normalized = normalizedBounds(bounds);
  return [
    intervalTs.toISOString(),
    normalized.rowLimit,
    normalized.rowPreset,
    normalized.constraintType,
    normalized.constraintSearch,
    normalized.settlementPointSearch,
    normalized.pinnedConstraints.join(","),
    normalized.pinnedSettlementPoints.join(","),
    normalized.columnSet,
    normalized.columnLimit,
    normalized.orientation,
    normalized.rowOrder,
    normalized.peekConstraint,
    normalized.peekSettlementPoint,
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
    normalized.rowPreset,
    normalized.constraintType,
    normalized.constraintSearch,
    normalized.settlementPointSearch,
    normalized.pinnedConstraints.join(","),
    normalized.pinnedSettlementPoints.join(","),
    normalized.columnSet,
    normalized.columnLimit,
    normalized.orientation,
    normalized.rowOrder,
    normalized.peekConstraint,
    normalized.peekSettlementPoint,
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

  const normalized = normalizedBounds(bounds);
  const requestOptions: MatrixFrameRequest = {
    ...normalized,
    constraintType: normalized.constraintType || undefined,
    signal,
  };
  const frame = await fetchMatrixFrame(intervalTs, requestOptions);
  return remember(request, frame, bounds);
}

export function clearMatrixFrameCache(): void {
  requestIndex.clear();
  frames.clear();
}
