import type { MatrixColumn, MatrixFrame, MatrixRow } from "../../api/types";
import {
  formatMatrixMu,
  formatMatrixValue,
  matrixCellSf,
  matrixContribution,
  type MatrixSelection,
} from "../../lib/matrix";

interface Props {
  frame: MatrixFrame;
  selection: MatrixSelection;
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
}

function mapHref(kind: "constraint" | "sp", value: string) {
  return `/map?${kind}=${encodeURIComponent(value)}`;
}

function valueOrDash(value: string | null | undefined) {
  return value || "-";
}

function rowFor(frame: MatrixFrame, key: string): [MatrixRow, number] | null {
  const index = frame.rows.findIndex((row) => row.constraint_key === key);
  return index < 0 ? null : [frame.rows[index], index];
}

function columnFor(frame: MatrixFrame, point: string): [MatrixColumn, number] | null {
  const index = frame.columns.findIndex((column) => column.settlement_point === point);
  return index < 0 ? null : [frame.columns[index], index];
}

function CellDetails({ frame, constraintKey, settlementPoint }: { frame: MatrixFrame; constraintKey: string; settlementPoint: string }) {
  const row = rowFor(frame, constraintKey);
  const column = columnFor(frame, settlementPoint);
  if (!row || !column) return null;
  const [constraint, rowIndex] = row;
  const [point, columnIndex] = column;
  const sf = matrixCellSf(frame.sf.values, rowIndex, columnIndex, frame.columns.length);
  const forecast = matrixContribution(sf, constraint.forecast_mu);
  const dam = matrixContribution(sf, constraint.ercot_dam_mu);
  return <>
    <h3>{constraint.constraint_name} × {point.settlement_point}</h3>
    <p className="matrix-inspector__key">{constraint.constraint_key}</p>
    <dl className="matrix-inspector__metrics">
      <div><dt>Implied SF</dt><dd>{formatMatrixValue(sf, "sf")}</dd></div>
      <div><dt>Forecast μ</dt><dd>{formatMatrixMu(constraint.forecast_mu)}</dd></div>
      <div><dt>−SF × Forecast μ</dt><dd>{formatMatrixValue(forecast, "contribution")}/MWh</dd></div>
      <div><dt>ERCOT DAM μ</dt><dd>{constraint.ercot_dam_mu == null ? "-" : formatMatrixMu(constraint.ercot_dam_mu)}</dd></div>
      <div><dt>−SF × DAM μ</dt><dd>{dam == null ? "-" : `${formatMatrixValue(dam, "contribution")}/MWh`}</dd></div>
    </dl>
    <p className="matrix-inspector__actions"><a href={mapHref("constraint", constraint.constraint_key)}>View constraint on map</a><a href={mapHref("sp", point.settlement_point)}>View settlement point on map</a></p>
  </>;
}

function ConstraintDetails({ frame, constraintKey }: { frame: MatrixFrame; constraintKey: string }) {
  const found = rowFor(frame, constraintKey);
  if (!found) return null;
  const [row, rowIndex] = found;
  const exposures = frame.columns.map((column, columnIndex) => ({
    point: column.settlement_point,
    sf: matrixCellSf(frame.sf.values, rowIndex, columnIndex, frame.columns.length),
  })).filter((exposure): exposure is { point: string; sf: number } => exposure.sf != null);
  const positive = exposures.filter((exposure) => exposure.sf > 0).sort((a, b) => b.sf - a.sf)[0];
  const negative = exposures.filter((exposure) => exposure.sf < 0).sort((a, b) => a.sf - b.sf)[0];
  return <>
    <h3>{row.constraint_name}</h3><p className="matrix-inspector__key"><span>Constraint key (name | contingency)</span>{row.constraint_key}</p>
    <dl className="matrix-inspector__metrics">
      <div><dt>Contingency</dt><dd>{valueOrDash(row.contingency_name)}</dd></div>
      {row.constraint_type != null && <div><dt>Matrix class</dt><dd>{row.constraint_type}</dd></div>}
      <div><dt>Daily rank</dt><dd>{row.daily_rank}</dd></div><div><dt>Binding</dt><dd>{row.binding_hours}</dd></div><div><dt>Maximum |SF|</dt><dd>{formatMatrixValue(row.max_abs_sf, "sf")}</dd></div>
      <div><dt>Forecast μ</dt><dd>{formatMatrixMu(row.forecast_mu)}</dd></div><div><dt>ERCOT DAM μ</dt><dd>{row.ercot_dam_mu == null ? "-" : formatMatrixMu(row.ercot_dam_mu)}</dd></div>
      <div><dt>Strongest positive exposure</dt><dd>{positive ? `${positive.point} (${formatMatrixValue(positive.sf, "sf")})` : "-"}</dd></div><div><dt>Strongest negative exposure</dt><dd>{negative ? `${negative.point} (${formatMatrixValue(negative.sf, "sf")})` : "-"}</dd></div>
    </dl><p className="matrix-inspector__actions"><a href={mapHref("constraint", row.constraint_key)}>View constraint on map</a></p>
  </>;
}

function SettlementPointDetails({ frame, settlementPoint }: { frame: MatrixFrame; settlementPoint: string }) {
  const found = columnFor(frame, settlementPoint);
  if (!found) return null;
  const [column, columnIndex] = found;
  const drivers = frame.rows.map((row, rowIndex) => ({ row, sf: matrixCellSf(frame.sf.values, rowIndex, columnIndex, frame.columns.length) })).filter((driver): driver is { row: MatrixRow; sf: number } => driver.sf != null).sort((a, b) => Math.abs(b.sf) - Math.abs(a.sf)).slice(0, 3);
  const sum = (source: "forecast_mu" | "ercot_dam_mu") => {
    let hasValue = false;
    const total = frame.rows.reduce((running, row, rowIndex) => {
      const contribution = matrixContribution(matrixCellSf(frame.sf.values, rowIndex, columnIndex, frame.columns.length), row[source]);
      if (contribution == null) return running;
      hasValue = true;
      return running + contribution;
    }, 0);
    return hasValue ? total : null;
  };
  const forecastSum = sum("forecast_mu");
  const damSum = sum("ercot_dam_mu");
  return <>
    <h3>{column.settlement_point}</h3>
    <dl className="matrix-inspector__metrics">
      <div><dt>Type</dt><dd>{valueOrDash(column.settlement_point_type)}</dd></div><div><dt>Load zone</dt><dd>{valueOrDash(column.load_zone)}</dd></div>
      <div><dt>Visible-row Forecast contribution</dt><dd>{forecastSum == null ? "-" : `${formatMatrixValue(forecastSum, "contribution")}/MWh`}</dd></div><div><dt>Visible-row DAM contribution</dt><dd>{damSum == null ? "-" : `${formatMatrixValue(damSum, "contribution")}/MWh`}</dd></div>
      <div><dt>Strongest visible drivers</dt><dd>{drivers.length ? drivers.map((driver) => `${driver.row.constraint_name} (${formatMatrixValue(driver.sf, "sf")})`).join(", ") : "-"}</dd></div>
    </dl>
    {(frame.rows_truncated || frame.columns_truncated) && <p className="matrix-inspector__warning">Visible-row sums are not total nodal congestion: this Matrix response is truncated.</p>}
    <p className="matrix-inspector__actions"><a href={mapHref("sp", column.settlement_point)}>View settlement point on map</a></p>
  </>;
}

export default function MatrixInspector({ frame, selection, collapsed, onCollapsedChange }: Props) {
  return <section className="matrix-inspector" aria-label="Selection inspector">
    <button className="matrix-inspector__collapse" type="button" aria-expanded={!collapsed} aria-label={collapsed ? "Expand inspector" : "Collapse inspector"} title={collapsed ? "Expand inspector" : "Collapse inspector"} onClick={() => onCollapsedChange(!collapsed)}><svg className={collapsed ? "is-collapsed" : ""} viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg></button>
    {collapsed ? <div className="matrix-inspector__collapsed-title">Selection Inspector.</div> : <div className="matrix-inspector__body">{selection?.kind === "cell" ? <CellDetails frame={frame} {...selection} /> : selection?.kind === "constraint" ? <ConstraintDetails frame={frame} {...selection} /> : selection?.kind === "settlementPoint" ? <SettlementPointDetails frame={frame} {...selection} /> : <p>Select a constraint row, settlement-point column, or cell to inspect its exact-hour values.</p>}</div>}
  </section>;
}
