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

/** Read or load a matrix frame; every response-affecting query parameter is keyed. */
export function getMatrixFrame(
  intervalTs: Date,
  bounds: MatrixFrameBounds = {},
): Promise<MatrixFrame> {
  const request = key({ intervalTs: intervalTs.toISOString(), ...normalizedBounds(bounds) });
  return frames.load(request, (signal) => fetchMatrixFrame(intervalTs, { ...bounds, signal }));
}
