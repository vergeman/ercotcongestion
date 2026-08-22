import { QueryCache } from "./cache";
import { fetchMatrixFrame, type MatrixFrameRequest } from "./matrix";
import type { MatrixFrame } from "./types";

const frames = new QueryCache<MatrixFrame>({ maxSize: 36, ttlMs: 5 * 60 * 1000 });

export type MatrixFrameBounds = Omit<MatrixFrameRequest, "signal">;

function normalizedBounds(bounds: MatrixFrameBounds = {}) {
  return {
    rowLimit: bounds.rowLimit ?? 30, columnLimit: bounds.columnLimit ?? 40,
    rowPreset: bounds.rowPreset ?? "top30",
    constraintType: bounds.constraintType ?? "",
    constraintSearch: bounds.constraintSearch ?? "",
    settlementPointSearch: bounds.settlementPointSearch ?? "",
    pinnedConstraints: [...(bounds.pinnedConstraints ?? [])].sort(),
    pinnedSettlementPoints: [...(bounds.pinnedSettlementPoints ?? [])].sort(),
    columnSet: bounds.columnSet ?? "core", orientation: bounds.orientation ?? "constraints",
    rowOrder: bounds.rowOrder ?? "contribution", peekConstraint: bounds.peekConstraint ?? "",
    peekSettlementPoint: bounds.peekSettlementPoint ?? "",
  };
}

function key(parts: Record<string, unknown>): string { return JSON.stringify(parts); }

export function matrixFrameCacheKey(
  frame: Pick<MatrixFrame, "run_id" | "delivery_date" | "interval_ts">,
  bounds: MatrixFrameBounds = {},
): string {
  return key({
    runId: frame.run_id,
    deliveryDate: frame.delivery_date,
    intervalTs: frame.interval_ts,
    ...normalizedBounds(bounds),
  });
}

/** Read or load a matrix frame; every response-affecting query parameter is keyed. */
export function getMatrixFrame(
  intervalTs: Date,
  bounds: MatrixFrameBounds = {},
  _signal?: AbortSignal,
): Promise<MatrixFrame> {
  const request = key({ intervalTs: intervalTs.toISOString(), ...normalizedBounds(bounds) });
  return frames.load(request, (signal) => fetchMatrixFrame(intervalTs, { ...bounds, signal }));
}

export function clearMatrixFrameCache(): void { frames.invalidate(); }
