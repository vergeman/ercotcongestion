import type { MatrixColumn, MatrixFrame, MatrixRow } from "../api/types";
import { congestionColor } from "./colors";

export type MatrixValueMode = "sf" | "contribution";
export type MatrixMuSource = "forecast" | "ercotDam";
export type MatrixSelection =
  | { kind: "constraint"; constraintKey: string }
  | { kind: "settlementPoint"; settlementPoint: string }
  | { kind: "cell"; constraintKey: string; settlementPoint: string }
  | null;

// 0139/0002: the sidebar index tab.
export type MatrixTab = "constraints" | "nodes";
// The stage lens — Read (detail, 0003) vs SF (the grid kept from before).
export type MatrixLens = "read" | "sf";
// The SF-lens value sub-toggle. Maps onto the existing (mode, muSource) pair
// below rather than replacing it, so MatrixGrid/MatrixLegend stay unchanged.
export type MatrixValTab = "sf" | "fmu" | "dmu";

export function matrixValueModeForVal(val: MatrixValTab): MatrixValueMode {
  return val === "sf" ? "sf" : "contribution";
}

export function matrixMuSourceForVal(val: MatrixValTab): MatrixMuSource {
  return val === "dmu" ? "ercotDam" : "forecast";
}

// The sidebar/workspace-level selection (0139/0002) — coarser than
// MatrixSelection above, which also carries the grid's cell selection.
export type MatrixEntitySelection =
  | { kind: "constraint"; key: string }
  | { kind: "node"; point: string }
  | null;

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

export function matrixDamUnavailableLabel(frame: Pick<MatrixFrame, "dam_status">): string {
  return frame.dam_status === "pending" ? "Not published" : "-";
}

export function formatMatrixDamMu(
  frame: Pick<MatrixFrame, "dam_status">,
  value: number | null
): string {
  return value == null ? matrixDamUnavailableLabel(frame) : formatMatrixMu(value);
}

export function matrixMuForSource(row: MatrixRow, source: MatrixMuSource): number | null {
  return source === "forecast" ? row.forecast_mu : row.ercot_dam_mu;
}

export interface MatrixCellMetadata {
  constraint: MatrixRow;
  column: MatrixColumn;
  rowIndex: number;
  columnIndex: number;
  sf: number | null;
  forecastContribution: number | null;
  damContribution: number | null;
}

export function matrixCellMetadata(
  frame: MatrixFrame,
  rowIndex: number,
  columnIndex: number
): MatrixCellMetadata | null {
  const constraint = frame.rows[rowIndex];
  const column = frame.columns[columnIndex];
  if (!constraint || !column) return null;
  const sf = matrixCellSf(frame.sf.values, rowIndex, columnIndex, frame.columns.length);
  return {
    constraint,
    column,
    rowIndex,
    columnIndex,
    sf,
    forecastContribution: matrixContribution(sf, constraint.forecast_mu),
    damContribution: matrixContribution(sf, constraint.ercot_dam_mu),
  };
}

export function matrixColumnContributionSum(
  frame: MatrixFrame,
  columnIndex: number,
  source: MatrixMuSource
): number | null {
  let hasValue = false;
  const total = frame.rows.reduce((running, row, rowIndex) => {
    const contribution = matrixContribution(
      matrixCellSf(frame.sf.values, rowIndex, columnIndex, frame.columns.length),
      matrixMuForSource(row, source)
    );
    if (contribution == null) return running;
    hasValue = true;
    return running + contribution;
  }, 0);
  return hasValue ? total : null;
}
