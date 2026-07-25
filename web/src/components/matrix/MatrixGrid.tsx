import { useCallback, useEffect, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { MatrixFrame } from "../../api/types";
import { TooltipBubble } from "../ui/Tooltip";
import {
  formatMatrixDamMu,
  formatMatrixMu,
  formatMatrixValue,
  matrixCellMetadata,
  matrixColumnContributionSum,
  matrixContribution,
  matrixMuForSource,
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
  maxAbs: number;
  onSelect: (selection: MatrixSelection) => void;
}

type MatrixTooltipTarget =
  | { kind: "row"; rowIndex: number; element: HTMLElement }
  | { kind: "column"; columnIndex: number; element: HTMLElement }
  | { kind: "cell"; rowIndex: number; columnIndex: number; element: HTMLElement };

const tooltipId = "matrix-grid-tooltip";

function valueOrUnknown(value: string | null) {
  return value || "Unknown";
}

function contributionText(value: number | null, unavailable: string) {
  return value == null ? unavailable : `${formatMatrixValue(value, "contribution")}/MWh`;
}

function damText(value: number | null) {
  return value == null ? "-" : formatMatrixMu(value);
}

function MatrixTooltipDetails({
  title,
  subtitle,
  rows,
}: {
  title: string;
  subtitle?: string;
  rows: Array<[label: string, value: ReactNode]>;
}) {
  return <div className="matrix-tooltip">
    <div className="matrix-tooltip__header">
      <b>{title}</b>
      {subtitle && <span>{subtitle}</span>}
    </div>
    <div className="matrix-tooltip__body">
      {rows.map(([label, value]) => <div className="matrix-tooltip__row" key={label}>
        <span>{label}</span><strong>{value}</strong>
      </div>)}
    </div>
  </div>;
}

function MatrixTooltipContent({
  frame,
  target,
  muSource,
}: {
  frame: MatrixFrame;
  target: MatrixTooltipTarget;
  muSource: MatrixMuSource;
}): ReactNode {
  if (target.kind === "cell") {
    const metadata = matrixCellMetadata(frame, target.rowIndex, target.columnIndex);
    if (!metadata) return null;
    const { constraint, column } = metadata;
    return <MatrixTooltipDetails title={constraint.constraint_name} subtitle={constraint.constraint_key} rows={[
      ["Contingency", valueOrUnknown(constraint.contingency_name)],
      ["Settlement point", column.settlement_point],
      ["Implied SF", formatMatrixValue(metadata.sf, "sf")],
      ["Forecast μ", formatMatrixMu(constraint.forecast_mu)],
      ["Forecast contribution", contributionText(metadata.forecastContribution, "-")],
      ["ERCOT DAM μ", damText(constraint.ercot_dam_mu)],
      ["DAM contribution", contributionText(metadata.damContribution, "-")],
    ]} />;
  }

  if (target.kind === "row") {
    const row = frame.rows[target.rowIndex];
    if (!row) return null;
    return <MatrixTooltipDetails title={row.constraint_name} subtitle={row.constraint_key} rows={[
      ["Contingency", valueOrUnknown(row.contingency_name)],
      ["Constraint type", valueOrUnknown(row.constraint_type)],
      ["Daily contribution rank", row.daily_rank],
      ["Selected-hour Forecast μ", formatMatrixMu(row.forecast_mu)],
      ["Selected-hour ERCOT DAM μ", damText(row.ercot_dam_mu)],
      ["Binding hours", row.binding_hours],
      ["Maximum |SF|", formatMatrixValue(row.max_abs_sf, "sf")],
    ]} />;
  }

  const column = frame.columns[target.columnIndex];
  if (!column) return null;
  const sourceLabel = muSource === "forecast" ? "Forecast" : "ERCOT DAM";
  const contribution = matrixColumnContributionSum(frame, target.columnIndex, muSource);
  return <MatrixTooltipDetails title={column.settlement_point} rows={[
    ["Settlement-point type", valueOrUnknown(column.settlement_point_type)],
    ["Load zone", valueOrUnknown(column.load_zone)],
    ["Maximum |SF|", formatMatrixValue(column.max_abs_sf, "sf")],
    [`Visible-row ${sourceLabel} contribution`, contributionText(contribution, "-")],
  ]} />;
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

export default function MatrixGrid({ frame, mode, muSource, selection, maxAbs, onSelect }: Props) {
  const [tooltip, setTooltip] = useState<MatrixTooltipTarget | null>(null);
  const hideTooltip = useCallback(() => setTooltip(null), []);

  useEffect(() => {
    if (!selection) return;
    const target = document.getElementById(selectionElementId(selection));
    if (!target) return;
    target.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
  }, [selection]);

  useEffect(() => {
    if (!tooltip) return;
    window.addEventListener("scroll", hideTooltip, true);
    window.addEventListener("resize", hideTooltip);
    return () => {
      window.removeEventListener("scroll", hideTooltip, true);
      window.removeEventListener("resize", hideTooltip);
    };
  }, [tooltip, hideTooltip]);

  const showTooltip = useCallback((event: { currentTarget: HTMLElement; target: EventTarget | null }) => {
    if (!(event.target instanceof Element)) return;
    const element = event.target.closest<HTMLElement>("[data-matrix-tooltip]");
    if (!element || !event.currentTarget.contains(element)) return;
    const rowIndex = Number(element.dataset.matrixRow);
    const columnIndex = Number(element.dataset.matrixColumn);
    const kind = element.dataset.matrixTooltip;
    const next = kind === "row" && Number.isInteger(rowIndex)
      ? { kind, rowIndex, element } as MatrixTooltipTarget
      : kind === "column" && Number.isInteger(columnIndex)
        ? { kind, columnIndex, element } as MatrixTooltipTarget
        : kind === "cell" && Number.isInteger(rowIndex) && Number.isInteger(columnIndex)
          ? { kind, rowIndex, columnIndex, element } as MatrixTooltipTarget
          : null;
    if (next) setTooltip((current) => current?.element === element ? current : next);
  }, []);

  const isContribution = mode === "contribution";
  const sourceLabel = muSource === "forecast" ? "Forecast μ" : "ERCOT DAM μ";
  const unit = isContribution ? "$/MWh" : "dimensionless implied shift factor";

  return (
    <div className="matrix-grid" role="region" aria-label="Constraint by settlement point matrix" tabIndex={0} onMouseOver={showTooltip} onMouseLeave={hideTooltip} onFocus={showTooltip} onBlur={hideTooltip}>
      <table>
        <thead>
          <tr>
            <th className="matrix-grid__corner" scope="col">
              <span>Constraint</span>
              <small>{isContribution ? sourceLabel : "recovered implied SF"}</small>
            </th>
            {frame.columns.map((column, columnIndex) => (
              <th
                key={column.settlement_point}
                className="matrix-grid__column"
                scope="col"
                tabIndex={0}
                id={selectionElementId({ kind: "settlementPoint", settlementPoint: column.settlement_point })}
                aria-selected={selection?.kind === "settlementPoint" && selection.settlementPoint === column.settlement_point}
                aria-label={`Settlement point ${column.settlement_point}${column.load_zone ? `, ${column.load_zone}` : ""}`}
                aria-describedby={tooltipId}
                data-matrix-tooltip="column"
                data-matrix-column={columnIndex}
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
            const mu = matrixMuForSource(row, muSource);
            return (
              <tr key={row.constraint_key}>
                <th
                  className="matrix-grid__row"
                  scope="row"
                  tabIndex={0}
                  id={selectionElementId({ kind: "constraint", constraintKey: row.constraint_key })}
                  aria-selected={selection?.kind === "constraint" && selection.constraintKey === row.constraint_key}
                  aria-label={`Constraint ${row.constraint_name}; ${sourceLabel} ${muSource === "ercotDam" ? formatMatrixDamMu(frame, mu) : formatMatrixMu(mu)}`}
                  aria-describedby={tooltipId}
                  data-matrix-tooltip="row"
                  data-matrix-row={rowIndex}
                  onClick={() => onSelect({ kind: "constraint", constraintKey: row.constraint_key })}
                  onKeyDown={(event) => selectOnKey(event, () => onSelect({ kind: "constraint", constraintKey: row.constraint_key }))}
                >
                  <span>{row.constraint_name}</span>
                  <small>{isContribution ? `${sourceLabel} ${muSource === "ercotDam" ? formatMatrixDamMu(frame, mu) : formatMatrixMu(mu)}` : `rank ${row.daily_rank}`}</small>
                </th>
                {frame.columns.map((column, columnIndex) => {
                  const sf = matrixCellMetadata(frame, rowIndex, columnIndex)?.sf ?? null;
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
                      aria-describedby={tooltipId}
                      data-matrix-tooltip="cell"
                      data-matrix-row={rowIndex}
                      data-matrix-column={columnIndex}
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
      {tooltip ? createPortal(
        <TooltipBubble className="tt--matrix" anchor={tooltip.element.getBoundingClientRect()} placement={tooltip.kind === "column" ? "bottom" : "right"}>
          <MatrixTooltipContent frame={frame} target={tooltip} muSource={muSource} />
        </TooltipBubble>,
        document.body
      ) : null}
    </div>
  );
}
