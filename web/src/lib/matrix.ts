import { congestionColor } from "./colors";

export type MatrixValueMode = "sf" | "contribution";
export type MatrixMuSource = "forecast" | "ercotDam";

export function matrixCellSf(
  values: number[],
  rowIndex: number,
  columnIndex: number,
  columnCount: number
): number | null {
  const value = values[rowIndex * columnCount + columnIndex];
  return Number.isFinite(value) ? value : null;
}

// Contribution is deliberately client-side: both μ sources share the returned,
// recovered implied SF field and only the selected row μ changes.
export function matrixContribution(sf: number | null, mu: number | null): number | null {
  return sf == null || mu == null ? null : -sf * mu;
}

export function matrixValueColor(value: number | null, maxAbs: number): string {
  if (value == null || maxAbs <= 0) return "var(--bg-surface)";
  // The Matrix's SF convention is export/+ → blue and import/− → red, the
  // inverse of the congestion map's import/+ convention.
  return congestionColor(-value / maxAbs);
}

export function formatMatrixValue(value: number | null, mode: MatrixValueMode): string {
  if (value == null) return "—";
  if (mode === "sf") return value.toFixed(3);
  return `$${value.toFixed(2)}`;
}

export function formatMatrixMu(value: number | null): string {
  return value == null ? "—" : `$${value.toFixed(2)}`;
}
