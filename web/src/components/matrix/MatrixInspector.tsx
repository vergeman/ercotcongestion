import type { ReactNode } from "react";
import type { MatrixColumn, MatrixFrame, MatrixRow } from "../../api/types";
import {
  formatMatrixDamMu,
  formatMatrixMu,
  formatMatrixValue,
  matrixCellMetadata,
  matrixColumnContributionSum,
  type MatrixSelection,
} from "../../lib/matrix";

interface Props {
  frame: MatrixFrame;
  selection: MatrixSelection;
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  onNavigateToMap: (search: string) => void;
  pinnedConstraints: string[];
  pinnedSettlementPoints: string[];
  onToggleConstraintPin: (constraintKey: string) => void;
  onToggleSettlementPointPin: (settlementPoint: string) => void;
}

function mapHref(kind: "constraint" | "sp", value: string) {
  return `/map?${kind}=${encodeURIComponent(value)}`;
}

function MapLink({ kind, value, children, onNavigateToMap }: { kind: "constraint" | "sp"; value: string; children: string; onNavigateToMap: (search: string) => void }) {
  const href = mapHref(kind, value);
  return <a href={href} onClick={(event) => {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    onNavigateToMap(new URL(href, window.location.origin).search);
  }}>{children}</a>;
}

function valueOrDash(value: string | null | undefined) {
  return value || "-";
}

function formatMatrixClass(value: string | null | undefined) {
  const matrixClass = valueOrDash(value);
  if (matrixClass === "gtc") return "GTC";
  return matrixClass === "-" ? matrixClass : `${matrixClass[0].toUpperCase()}${matrixClass.slice(1)}`;
}

function rowFor(frame: MatrixFrame, key: string): [MatrixRow, number] | null {
  const index = frame.rows.findIndex((row) => row.constraint_key === key);
  return index < 0 ? null : [frame.rows[index], index];
}

function columnFor(frame: MatrixFrame, point: string): [MatrixColumn, number] | null {
  const index = frame.columns.findIndex((column) => column.settlement_point === point);
  return index < 0 ? null : [frame.columns[index], index];
}

type DetailRow = [attribute: string, value: ReactNode];

function InspectorTable({ title, identity, core, details }: { title: string; identity: DetailRow[]; core: DetailRow[]; details: DetailRow[] }) {
  const leftRows = [...identity, ...details];
  const rowCount = Math.max(leftRows.length, core.length);
  return <div className="matrix-inspector__table-wrap">
    <h3>{title}</h3>
    <table className="matrix-inspector__table">
      <thead><tr><th>Attribute</th><th>Value</th><th>Core metrics</th><th>Value</th></tr></thead>
      <tbody>{Array.from({ length: rowCount }, (_, index) => {
        const left = leftRows[index];
        const right = core[index];
        return <tr key={index}>
          {left ? <><th scope="row">{left[0]}</th><td>{left[1]}</td></> : <><td /><td /></>}
          {right ? <><th scope="row">{right[0]}</th><td>{right[1]}</td></> : <><td /><td /></>}
        </tr>;
      })}</tbody>
    </table>
  </div>;
}

function CellDetails({ frame, constraintKey, settlementPoint, onNavigateToMap, constraintPin, settlementPointPin }: { frame: MatrixFrame; constraintKey: string; settlementPoint: string; onNavigateToMap: (search: string) => void; constraintPin: ReactNode; settlementPointPin: ReactNode }) {
  const row = rowFor(frame, constraintKey);
  const column = columnFor(frame, settlementPoint);
  if (!row || !column) return null;
  const [constraint, rowIndex] = row;
  const [point, columnIndex] = column;
  const metadata = matrixCellMetadata(frame, rowIndex, columnIndex);
  if (!metadata) return null;
  return <InspectorTable title={`${constraint.constraint_name} × ${point.settlement_point}`} identity={[["Constraint key", constraint.constraint_key], ["Pin Constraint", constraintPin], ["Pin Settlement Point", settlementPointPin], ["Map Constraint", <MapLink kind="constraint" value={constraint.constraint_key} onNavigateToMap={onNavigateToMap}>{constraint.constraint_name}</MapLink>], ["Map Settlement Point", <MapLink kind="sp" value={point.settlement_point} onNavigateToMap={onNavigateToMap}>{point.settlement_point}</MapLink>]]} core={[["Forecast μ", formatMatrixMu(constraint.forecast_mu)], ["ERCOT DAM μ", formatMatrixDamMu(frame, constraint.ercot_dam_mu)], ["Implied SF", formatMatrixValue(metadata.sf, "sf")], ["Forecast contribution", `${formatMatrixValue(metadata.forecastContribution, "contribution")}/MWh`], ["DAM contribution", metadata.damContribution == null ? formatMatrixDamMu(frame, constraint.ercot_dam_mu) : `${formatMatrixValue(metadata.damContribution, "contribution")}/MWh`]]} details={[["Contingency", valueOrDash(constraint.contingency_name)], ["Matrix class", formatMatrixClass(constraint.constraint_type)], ["Settlement point type", valueOrDash(point.settlement_point_type)], ["Load zone", valueOrDash(point.load_zone)]]} />;
}

function ConstraintDetails({ frame, constraintKey, onNavigateToMap, constraintPin }: { frame: MatrixFrame; constraintKey: string; onNavigateToMap: (search: string) => void; constraintPin: ReactNode }) {
  const found = rowFor(frame, constraintKey);
  if (!found) return null;
  const [row, rowIndex] = found;
  const exposures = frame.columns.map((column, columnIndex) => ({
    point: column.settlement_point,
    sf: matrixCellMetadata(frame, rowIndex, columnIndex)?.sf ?? null,
  })).filter((exposure): exposure is { point: string; sf: number } => exposure.sf != null);
  const positive = exposures.filter((exposure) => exposure.sf > 0).sort((a, b) => b.sf - a.sf)[0];
  const negative = exposures.filter((exposure) => exposure.sf < 0).sort((a, b) => a.sf - b.sf)[0];
  return <InspectorTable title={row.constraint_name} identity={[["Constraint key", row.constraint_key], ["Pin Constraint", constraintPin], ["Map Constraint", <MapLink kind="constraint" value={row.constraint_key} onNavigateToMap={onNavigateToMap}>{row.constraint_name}</MapLink>]]} core={[["Daily rank", row.daily_rank], ["Binding hours", row.binding_hours], ["Maximum |SF|", formatMatrixValue(row.max_abs_sf, "sf")], ["Forecast μ", formatMatrixMu(row.forecast_mu)], ["ERCOT DAM μ", formatMatrixDamMu(frame, row.ercot_dam_mu)], ["Strongest positive exposure", positive ? `${positive.point} (${formatMatrixValue(positive.sf, "sf")})` : "-"], ["Strongest negative exposure", negative ? `${negative.point} (${formatMatrixValue(negative.sf, "sf")})` : "-"]]} details={[["Contingency", valueOrDash(row.contingency_name)], ["Matrix class", formatMatrixClass(row.constraint_type)]]} />;
}

function SettlementPointDetails({ frame, settlementPoint, onNavigateToMap, settlementPointPin }: { frame: MatrixFrame; settlementPoint: string; onNavigateToMap: (search: string) => void; settlementPointPin: ReactNode }) {
  const found = columnFor(frame, settlementPoint);
  if (!found) return null;
  const [column, columnIndex] = found;
  const drivers = frame.rows.map((row, rowIndex) => ({ row, sf: matrixCellMetadata(frame, rowIndex, columnIndex)?.sf ?? null })).filter((driver): driver is { row: MatrixRow; sf: number } => driver.sf != null).sort((a, b) => Math.abs(b.sf) - Math.abs(a.sf)).slice(0, 3);
  const forecastSum = matrixColumnContributionSum(frame, columnIndex, "forecast");
  const damSum = matrixColumnContributionSum(frame, columnIndex, "ercotDam");
  return <InspectorTable title={column.settlement_point} identity={[["Settlement point", column.settlement_point], ["Pin Settlement Point", settlementPointPin], ["Map Settlement Point", <MapLink kind="sp" value={column.settlement_point} onNavigateToMap={onNavigateToMap}>{column.settlement_point}</MapLink>]]} core={[["Maximum |SF|", formatMatrixValue(column.max_abs_sf, "sf")], ["Forecast contribution", forecastSum == null ? "-" : `${formatMatrixValue(forecastSum, "contribution")}/MWh`], ["DAM contribution", damSum == null ? formatMatrixDamMu(frame, null) : `${formatMatrixValue(damSum, "contribution")}/MWh`], ["Strongest visible drivers", drivers.length ? drivers.map((driver) => `${driver.row.constraint_name} (${formatMatrixValue(driver.sf, "sf")})`).join(", ") : "-"]]} details={[["Type", valueOrDash(column.settlement_point_type)], ["Load zone", valueOrDash(column.load_zone)]]} />;
}

export default function MatrixInspector({ frame, selection, collapsed, onCollapsedChange, onNavigateToMap, pinnedConstraints, pinnedSettlementPoints, onToggleConstraintPin, onToggleSettlementPointPin }: Props) {
  const constraintPin = selection && (selection.kind === "constraint" || selection.kind === "cell")
    ? <input className="matrix-inspector__pin" type="checkbox" aria-label="Pin constraint" checked={pinnedConstraints.includes(selection.constraintKey)} onChange={() => onToggleConstraintPin(selection.constraintKey)} /> : null;
  const settlementPointPin = selection && (selection.kind === "settlementPoint" || selection.kind === "cell")
    ? <input className="matrix-inspector__pin" type="checkbox" aria-label="Pin settlement point" checked={pinnedSettlementPoints.includes(selection.settlementPoint)} onChange={() => onToggleSettlementPointPin(selection.settlementPoint)} /> : null;
  return <section className="matrix-inspector" aria-label="Selection inspector">
    <button className="matrix-inspector__collapse" type="button" aria-expanded={!collapsed} aria-label={collapsed ? "Expand inspector" : "Collapse inspector"} title={collapsed ? "Expand inspector" : "Collapse inspector"} onClick={() => onCollapsedChange(!collapsed)}><svg className={collapsed ? "is-collapsed" : ""} viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg></button>
    {collapsed ? <div className="matrix-inspector__collapsed-title">Selection Inspector.</div> : <div className="matrix-inspector__body">{selection?.kind === "cell" ? <CellDetails frame={frame} {...selection} onNavigateToMap={onNavigateToMap} constraintPin={constraintPin} settlementPointPin={settlementPointPin} /> : selection?.kind === "constraint" ? <ConstraintDetails frame={frame} {...selection} onNavigateToMap={onNavigateToMap} constraintPin={constraintPin} /> : selection?.kind === "settlementPoint" ? <SettlementPointDetails frame={frame} {...selection} onNavigateToMap={onNavigateToMap} settlementPointPin={settlementPointPin} /> : <p>Select a constraint row, settlement-point column, or cell to inspect its exact-hour values.</p>}</div>}
  </section>;
}
