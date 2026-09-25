import type { MatrixColumn, MatrixFrame, MatrixOrientation, MatrixRow } from "../api/types";
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
// The stage lens — Read (detail, 0003), SF (the grid kept from before), and
// Basis (0139/0006: a full-screen two-node congestion basis, Nodes tab only).
export type MatrixLens = "read" | "sf" | "basis";
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
  // The Matrix's SF convention is positive → blue and negative → red.
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

// One entity on a visual axis of the grid. The wire is always constraint-major,
// so each item carries its native wire index (into `frame.rows` for a
// constraint, `frame.columns` for a settlement point); the grid resolves a
// cell's SF from the constraint and node indices regardless of which is drawn
// as the row. `kind` is reused directly as a `MatrixSelection` discriminator.
export type MatrixAxisKind = "constraint" | "settlementPoint";

export type MatrixAxisItem =
  | { kind: "constraint"; key: string; index: number; row: MatrixRow }
  | { kind: "settlementPoint"; key: string; index: number; column: MatrixColumn };

export interface MatrixDisplayAxes {
  transposed: boolean;
  rowKind: MatrixAxisKind;
  columnKind: MatrixAxisKind;
  displayRows: MatrixAxisItem[];
  displayColumns: MatrixAxisItem[];
}

// Single source of truth for the grid's visual orientation. `constraints`
// draws constraints as rows / nodes as columns (today's layout); `nodes`
// transposes — nodes as rows, constraints as columns — over the same
// already-correct constraint-major rectangle. The orientation is a *display*
// choice, decoupled from how the frame was fetched: the SF-lens rotation set is
// one stable rectangle the tab flips client-side without any refetch. Defaults
// to the frame's own `orientation` for callers that don't drive it explicitly.
export function matrixDisplayAxes(
  frame: MatrixFrame,
  orientation: MatrixOrientation = frame.orientation,
  // The previewed entity's key — hoisted to the first display row so the
  // "top row = current selection" reads regardless of the underlying order.
  topRowKey?: string | null,
): MatrixDisplayAxes {
  const constraintItems: MatrixAxisItem[] = frame.rows.map((row, index) => ({
    kind: "constraint", key: row.constraint_key, index, row,
  }));
  const nodeItems: MatrixAxisItem[] = frame.columns.map((column, index) => ({
    kind: "settlementPoint", key: column.settlement_point, index, column,
  }));
  const displayRows = orientation === "nodes" ? nodeItems : constraintItems;
  const displayColumns = orientation === "nodes" ? constraintItems : nodeItems;
  hoistToFront(displayRows, topRowKey);
  return orientation === "nodes"
    ? { transposed: true, rowKind: "settlementPoint", columnKind: "constraint", displayRows, displayColumns }
    : { transposed: false, rowKind: "constraint", columnKind: "settlementPoint", displayRows, displayColumns };
}

function hoistToFront(items: MatrixAxisItem[], key: string | null | undefined): void {
  if (!key) return;
  const at = items.findIndex((item) => item.key === key);
  if (at > 0) items.unshift(items.splice(at, 1)[0]);
}

// Resolve a cell's implied SF from one row-axis and one column-axis item,
// whichever orientation they came from: exactly one is the constraint and one
// the node, and the wire lookup is always SF[constraintIndex, nodeIndex].
export function matrixAxisCellSf(frame: MatrixFrame, a: MatrixAxisItem, b: MatrixAxisItem): number | null {
  const constraint = a.kind === "constraint" ? a : b.kind === "constraint" ? b : null;
  const node = a.kind === "settlementPoint" ? a : b.kind === "settlementPoint" ? b : null;
  if (!constraint || !node) return null;
  return matrixCellSf(frame.sf.values, constraint.index, node.index, frame.columns.length);
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
