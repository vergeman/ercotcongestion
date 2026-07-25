import { useEffect, type KeyboardEvent } from "react";
import type { MatrixFrame } from "../../api/types";
import {
  formatMatrixMu,
  formatMatrixValue,
  matrixCellSf,
  matrixContribution,
  matrixValueColor,
  type MatrixSelection,
  type MatrixMuSource,
  type MatrixValueMode,
} from "../../lib/matrix";

interface Props {
  frame: MatrixFrame;
  mode: MatrixValueMode;
  muSource: MatrixMuSource;
  selection: MatrixSelection;
  onSelect: (selection: MatrixSelection) => void;
}

function selectOnKey(
  event: KeyboardEvent<HTMLElement>,
  select: () => void
) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    select();
  }
}

function selectionElementId(selection: Exclude<MatrixSelection, null>) {
  const part = (value: string) => {
    const encoded = encodeURIComponent(value);
    return `${encoded.length}-${encoded}`;
  };
  return selection.kind === "constraint" ? `matrix-constraint-${part(selection.constraintKey)}` :
    selection.kind === "settlementPoint" ? `matrix-sp-${part(selection.settlementPoint)}` :
      `matrix-cell-${part(selection.constraintKey)}-${part(selection.settlementPoint)}`;
}

export default function MatrixGrid({ frame, mode, muSource, selection, onSelect }: Props) {
  useEffect(() => {
    if (!selection) return;
    const target = document.getElementById(selectionElementId(selection));
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
  }, [selection]);

  const isContribution = mode === "contribution";
  const values = frame.rows.flatMap((row, rowIndex) =>
    frame.columns.map((_, columnIndex) => {
      const sf = matrixCellSf(frame.sf.values, rowIndex, columnIndex, frame.columns.length);
      return isContribution
        ? matrixContribution(sf, muSource === "forecast" ? row.forecast_mu : row.ercot_dam_mu)
        : sf;
    })
  );
  const maxAbs = Math.max(0, ...values.flatMap((value) => value == null ? [] : [Math.abs(value)]));
  const sourceLabel = muSource === "forecast" ? "Forecast μ" : "ERCOT DAM μ";
  const unit = isContribution ? "$/MWh" : "dimensionless implied shift factor";

  return (
    <div className="matrix-grid" role="region" aria-label="Constraint by settlement point matrix" tabIndex={0}>
      <table>
        <thead>
          <tr>
            <th className="matrix-grid__corner" scope="col">
              <span>Constraint</span>
              <small>{isContribution ? sourceLabel : "recovered implied SF"}</small>
            </th>
            {frame.columns.map((column) => (
              <th
                key={column.settlement_point}
                className="matrix-grid__column"
                scope="col"
                tabIndex={0}
                id={selectionElementId({ kind: "settlementPoint", settlementPoint: column.settlement_point })}
                aria-selected={selection?.kind === "settlementPoint" && selection.settlementPoint === column.settlement_point}
                aria-label={`Settlement point ${column.settlement_point}${column.load_zone ? `, ${column.load_zone}` : ""}`}
                onClick={() => onSelect({ kind: "settlementPoint", settlementPoint: column.settlement_point })}
                onKeyDown={(event) => selectOnKey(event, () => onSelect({ kind: "settlementPoint", settlementPoint: column.settlement_point }))}
              >
                <span>{column.settlement_point}</span>
                {column.load_zone && <small>{column.load_zone}</small>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {frame.rows.map((row, rowIndex) => {
            const mu = muSource === "forecast" ? row.forecast_mu : row.ercot_dam_mu;
            return (
              <tr key={row.constraint_key}>
                <th
                  className="matrix-grid__row"
                  scope="row"
                  tabIndex={0}
                  id={selectionElementId({ kind: "constraint", constraintKey: row.constraint_key })}
                  aria-selected={selection?.kind === "constraint" && selection.constraintKey === row.constraint_key}
                  aria-label={`Constraint ${row.constraint_name}; ${sourceLabel} ${formatMatrixMu(mu)}`}
                  onClick={() => onSelect({ kind: "constraint", constraintKey: row.constraint_key })}
                  onKeyDown={(event) => selectOnKey(event, () => onSelect({ kind: "constraint", constraintKey: row.constraint_key }))}
                >
                  <span title={row.constraint_key}>{row.constraint_name}</span>
                  <small>{isContribution ? `${sourceLabel} ${formatMatrixMu(mu)}` : `rank ${row.daily_rank}`}</small>
                </th>
                {frame.columns.map((column, columnIndex) => {
                  const sf = matrixCellSf(frame.sf.values, rowIndex, columnIndex, frame.columns.length);
                  const value = isContribution ? matrixContribution(sf, mu) : sf;
                  const unavailable = value == null;
                  const selected = selection?.kind === "cell" && selection.constraintKey === row.constraint_key && selection.settlementPoint === column.settlement_point;
                  return (
                    <td
                      key={column.settlement_point}
                      className={`${unavailable ? "matrix-grid__cell matrix-grid__cell--unavailable" : "matrix-grid__cell"}${selected ? " is-selected" : ""}`}
                      tabIndex={0}
                      id={selectionElementId({ kind: "cell", constraintKey: row.constraint_key, settlementPoint: column.settlement_point })}
                      style={{ backgroundColor: matrixValueColor(value, maxAbs) }}
                      aria-selected={selected}
                      aria-label={`${row.constraint_name}, ${column.settlement_point}: ${unavailable ? "unavailable" : `${formatMatrixValue(value, mode)} ${unit}`}`}
                      onClick={() => onSelect({ kind: "cell", constraintKey: row.constraint_key, settlementPoint: column.settlement_point })}
                      onKeyDown={(event) => selectOnKey(event, () => onSelect({ kind: "cell", constraintKey: row.constraint_key, settlementPoint: column.settlement_point }))}
                    >
                      {formatMatrixValue(value, mode)}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
