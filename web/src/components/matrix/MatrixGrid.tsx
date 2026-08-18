import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { MatrixFrame, MatrixOrientation } from "../../api/types";
import { TooltipBubble } from "../ui/Tooltip";
import {
  formatMatrixDamMu,
  formatMatrixMu,
  formatMatrixValue,
  matrixAxisCellSf,
  matrixColumnContributionSum,
  matrixContribution,
  matrixDisplayAxes,
  matrixMuForSource,
  matrixValueColor,
  type MatrixAxisItem,
  type MatrixSelection,
  type MatrixMuSource,
  type MatrixValueMode,
} from "../../lib/matrix";

interface Props {
  frame: MatrixFrame;
  // The display orientation, driven by the sidebar tab — a pure client-side
  // transpose of the same fetched rectangle, so toggling never refetches.
  orientation: MatrixOrientation;
  // The previewed entity hoisted to the first display row (the "current
  // selection" top row). `previewKey` is that key only when it is *not* pinned —
  // the un-saved preview — so its header can read as a preview.
  topRowKey?: string | null;
  previewKey?: string | null;
  mode: MatrixValueMode;
  muSource: MatrixMuSource;
  selection: MatrixSelection;
  maxAbs: number;
  // `opts.shift` reports a shift/⌘-click so the workspace can route a node click
  // into the basis tray's slot B (0139/0006) instead of moving the selection.
  onSelect: (selection: MatrixSelection, opts?: { shift?: boolean }) => void;
  isPinned: (item: MatrixAxisItem) => boolean;
  onTogglePin: (item: MatrixAxisItem) => void;
}

type ConstraintItem = Extract<MatrixAxisItem, { kind: "constraint" }>;
type NodeItem = Extract<MatrixAxisItem, { kind: "settlementPoint" }>;

type MatrixTooltipTarget =
  | { kind: "constraint"; item: ConstraintItem; element: HTMLElement }
  | { kind: "settlementPoint"; item: NodeItem; element: HTMLElement }
  | { kind: "cell"; constraint: ConstraintItem; node: NodeItem; element: HTMLElement };

const tooltipId = "matrix-grid-tooltip";

// Exactly one of a row/column axis pair is the constraint and one the node,
// whichever orientation drew them; split so the SF cell identity stays
// SF[constraint, node] regardless of which axis is the visual row.
function splitAxis(a: MatrixAxisItem, b: MatrixAxisItem): { constraint: ConstraintItem | null; node: NodeItem | null } {
  const constraint = a.kind === "constraint" ? a : b.kind === "constraint" ? b : null;
  const node = a.kind === "settlementPoint" ? a : b.kind === "settlementPoint" ? b : null;
  return { constraint, node };
}

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

function constraintTooltip(item: ConstraintItem): ReactNode {
  const row = item.row;
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

function nodeTooltip(frame: MatrixFrame, item: NodeItem, muSource: MatrixMuSource): ReactNode {
  const column = item.column;
  const sourceLabel = muSource === "forecast" ? "Forecast" : "ERCOT DAM";
  const contribution = matrixColumnContributionSum(frame, item.index, muSource);
  return <MatrixTooltipDetails title={column.settlement_point} rows={[
    ["Settlement-point type", valueOrUnknown(column.settlement_point_type)],
    ["Load zone", valueOrUnknown(column.load_zone)],
    ["Maximum |SF|", formatMatrixValue(column.max_abs_sf, "sf")],
    [`Visible-row ${sourceLabel} contribution`, contributionText(contribution, "-")],
  ]} />;
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
  if (target.kind === "constraint") return constraintTooltip(target.item);
  if (target.kind === "settlementPoint") return nodeTooltip(frame, target.item, muSource);
  const { constraint, node } = target;
  const sf = matrixAxisCellSf(frame, constraint, node);
  return <MatrixTooltipDetails title={constraint.row.constraint_name} subtitle={constraint.row.constraint_key} rows={[
    ["Contingency", valueOrUnknown(constraint.row.contingency_name)],
    ["Settlement point", node.column.settlement_point],
    ["Implied SF", formatMatrixValue(sf, "sf")],
    ["Forecast μ", formatMatrixMu(constraint.row.forecast_mu)],
    ["Forecast contribution", contributionText(matrixContribution(sf, constraint.row.forecast_mu), "-")],
    ["ERCOT DAM μ", damText(constraint.row.ercot_dam_mu)],
    ["DAM contribution", contributionText(matrixContribution(sf, constraint.row.ercot_dam_mu), "-")],
  ]} />;
}

function selectOnKey(event: KeyboardEvent<HTMLElement>, select: () => void) {
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

// An axis entity's stable element id / selection, keyed by the entity itself so
// scroll-to-selection follows the entity across a transpose, not a row/col slot.
function axisSelection(item: MatrixAxisItem): Exclude<MatrixSelection, null> {
  return item.kind === "constraint"
    ? { kind: "constraint", constraintKey: item.key }
    : { kind: "settlementPoint", settlementPoint: item.key };
}

function isItemSelected(selection: MatrixSelection, item: MatrixAxisItem): boolean {
  if (!selection) return false;
  if (item.kind === "constraint") return selection.kind === "constraint" && selection.constraintKey === item.key;
  return selection.kind === "settlementPoint" && selection.settlementPoint === item.key;
}

function PinStar({ pinned, label, onToggle }: { pinned: boolean; label: string; onToggle: () => void }) {
  return (
    <button
      type="button"
      className={`matrix-grid__pin${pinned ? " is-pinned" : ""}`}
      aria-label={label}
      aria-pressed={pinned}
      title={pinned ? "Unpin" : "Pin"}
      onClick={(event) => { event.stopPropagation(); onToggle(); }}
      onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") event.stopPropagation(); }}
    >
      {pinned ? "★" : "☆"}
    </button>
  );
}

function AxisHeaderBody({ frame, item, isContribution, sourceLabel, muSource }: {
  frame: MatrixFrame;
  item: MatrixAxisItem;
  isContribution: boolean;
  sourceLabel: string;
  muSource: MatrixMuSource;
}) {
  if (item.kind === "constraint") {
    const mu = matrixMuForSource(item.row, muSource);
    const muText = muSource === "ercotDam" ? formatMatrixDamMu(frame, mu) : formatMatrixMu(mu);
    return <>
      <span>{item.row.constraint_name}</span>
      <small>{isContribution ? `${sourceLabel} ${muText}` : `rank ${item.row.daily_rank}`}</small>
    </>;
  }
  return <>
    <span>{item.column.settlement_point}</span>
    {item.column.load_zone && <small>{item.column.load_zone}</small>}
  </>;
}

export default function MatrixGrid({ frame, orientation, topRowKey, previewKey, mode, muSource, selection, maxAbs, onSelect, isPinned, onTogglePin }: Props) {
  const [tooltip, setTooltip] = useState<MatrixTooltipTarget | null>(null);
  const hideTooltip = useCallback(() => setTooltip(null), []);

  const axes = useMemo(() => matrixDisplayAxes(frame, orientation, topRowKey), [frame, orientation, topRowKey]);
  const axesRef = useRef(axes);
  axesRef.current = axes;

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
    const current = axesRef.current;
    const rowIndex = Number(element.dataset.matrixRow);
    const columnIndex = Number(element.dataset.matrixColumn);
    const kind = element.dataset.matrixTooltip;
    let next: MatrixTooltipTarget | null = null;
    if (kind === "row" && Number.isInteger(rowIndex)) {
      const item = current.displayRows[rowIndex];
      if (item) next = item.kind === "constraint" ? { kind: "constraint", item, element } : { kind: "settlementPoint", item, element };
    } else if (kind === "column" && Number.isInteger(columnIndex)) {
      const item = current.displayColumns[columnIndex];
      if (item) next = item.kind === "constraint" ? { kind: "constraint", item, element } : { kind: "settlementPoint", item, element };
    } else if (kind === "cell" && Number.isInteger(rowIndex) && Number.isInteger(columnIndex)) {
      const { constraint, node } = splitAxis(current.displayRows[rowIndex], current.displayColumns[columnIndex]);
      if (constraint && node) next = { kind: "cell", constraint, node, element };
    }
    if (next) setTooltip((prev) => prev?.element === element ? prev : next);
  }, []);

  const isContribution = mode === "contribution";
  const sourceLabel = muSource === "forecast" ? "Forecast μ" : "ERCOT DAM μ";
  const unit = isContribution ? "$/MWh" : "dimensionless implied shift factor";
  const cornerLabel = axes.rowKind === "constraint" ? "Constraint" : "Settlement point";

  return (
    <div className="matrix-grid" role="region" aria-label="Constraint by settlement point matrix" tabIndex={0} onMouseOver={showTooltip} onMouseLeave={hideTooltip} onFocus={showTooltip} onBlur={hideTooltip}>
      <table>
        <thead>
          <tr>
            <th className="matrix-grid__corner" scope="col">
              <span>{cornerLabel}</span>
              <small>{isContribution ? sourceLabel : "recovered implied SF"}</small>
            </th>
            {axes.displayColumns.map((item, columnIndex) => (
              <th
                key={item.key}
                className={`matrix-grid__column${item.key === previewKey ? " matrix-grid__head--preview" : ""}`}
                scope="col"
                tabIndex={0}
                id={selectionElementId(axisSelection(item))}
                aria-selected={isItemSelected(selection, item)}
                aria-label={`${item.kind === "constraint" ? "Constraint" : "Settlement point"} ${item.key}`}
                aria-describedby={tooltipId}
                data-matrix-tooltip="column"
                data-matrix-column={columnIndex}
                onClick={(event) => onSelect(axisSelection(item), { shift: event.shiftKey || event.metaKey })}
                onKeyDown={(event) => selectOnKey(event, () => onSelect(axisSelection(item)))}
              >
                <PinStar pinned={isPinned(item)} label={`${isPinned(item) ? "Unpin" : "Pin"} ${item.key}`} onToggle={() => onTogglePin(item)} />
                <AxisHeaderBody frame={frame} item={item} isContribution={isContribution} sourceLabel={sourceLabel} muSource={muSource} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {axes.displayRows.map((rowItem, rowIndex) => (
            <tr key={rowItem.key}>
              <th
                className={`matrix-grid__row${rowItem.key === previewKey ? " matrix-grid__head--preview" : ""}`}
                scope="row"
                tabIndex={0}
                id={selectionElementId(axisSelection(rowItem))}
                aria-selected={isItemSelected(selection, rowItem)}
                aria-label={`${rowItem.kind === "constraint" ? "Constraint" : "Settlement point"} ${rowItem.key}`}
                aria-describedby={tooltipId}
                data-matrix-tooltip="row"
                data-matrix-row={rowIndex}
                onClick={(event) => onSelect(axisSelection(rowItem), { shift: event.shiftKey || event.metaKey })}
                onKeyDown={(event) => selectOnKey(event, () => onSelect(axisSelection(rowItem)))}
              >
                <PinStar pinned={isPinned(rowItem)} label={`${isPinned(rowItem) ? "Unpin" : "Pin"} ${rowItem.key}`} onToggle={() => onTogglePin(rowItem)} />
                <AxisHeaderBody frame={frame} item={rowItem} isContribution={isContribution} sourceLabel={sourceLabel} muSource={muSource} />
              </th>
              {axes.displayColumns.map((columnItem, columnIndex) => {
                const { constraint, node } = splitAxis(rowItem, columnItem);
                const sf = constraint && node ? matrixAxisCellSf(frame, constraint, node) : null;
                const mu = constraint ? matrixMuForSource(constraint.row, muSource) : null;
                const value = isContribution ? matrixContribution(sf, mu) : sf;
                const unavailable = value == null;
                const selected = Boolean(
                  selection?.kind === "cell" && constraint && node &&
                  selection.constraintKey === constraint.key && selection.settlementPoint === node.key
                );
                return (
                  <td
                    key={columnItem.key}
                    className={`${unavailable ? "matrix-grid__cell matrix-grid__cell--unavailable" : "matrix-grid__cell"}${selected ? " is-selected" : ""}`}
                    tabIndex={0}
                    id={constraint && node ? selectionElementId({ kind: "cell", constraintKey: constraint.key, settlementPoint: node.key }) : undefined}
                    style={{ backgroundColor: matrixValueColor(value, maxAbs) }}
                    aria-selected={selected}
                    aria-label={`${constraint?.row.constraint_name ?? rowItem.key}, ${node?.column.settlement_point ?? columnItem.key}: ${unavailable ? "unavailable" : `${formatMatrixValue(value, mode)} ${unit}`}`}
                    aria-describedby={tooltipId}
                    data-matrix-tooltip="cell"
                    data-matrix-row={rowIndex}
                    data-matrix-column={columnIndex}
                    onClick={(event) => { if (constraint && node) onSelect({ kind: "cell", constraintKey: constraint.key, settlementPoint: node.key }, { shift: event.shiftKey || event.metaKey }); }}
                    onKeyDown={(event) => selectOnKey(event, () => { if (constraint && node) onSelect({ kind: "cell", constraintKey: constraint.key, settlementPoint: node.key }); })}
                  >
                    {formatMatrixValue(value, mode)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {tooltip ? createPortal(
        <TooltipBubble className="tt--matrix" anchor={tooltip.element.getBoundingClientRect()} placement={tooltip.kind === "settlementPoint" && !axes.transposed ? "bottom" : tooltip.kind === "cell" ? "right" : axes.rowKind === tooltip.kind ? "right" : "bottom"}>
          <MatrixTooltipContent frame={frame} target={tooltip} muSource={muSource} />
        </TooltipBubble>,
        document.body
      ) : null}
      <style>{`
        .matrix-grid__row, .matrix-grid__column { padding-right: 22px; }
        .matrix-grid__pin { position: absolute; background: transparent; border: 0; color: var(--text-muted); cursor: pointer; font-size: 11px; line-height: 1; padding: 2px; z-index: 1; }
        .matrix-grid__pin.is-pinned { color: var(--accent); }
        .matrix-grid__pin:hover { color: var(--accent); }
        .matrix-grid__row .matrix-grid__pin { right: 3px; top: 50%; transform: translateY(-50%); }
        .matrix-grid__column .matrix-grid__pin { right: 3px; top: 3px; }
        /* The un-pinned preview header — a dashed accent edge that reads as
           "viewing, not saved" until the star is filled. */
        .matrix-grid__head--preview { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 45%, transparent); }
        .matrix-grid__row.matrix-grid__head--preview { border-left: 2px dashed var(--accent); }
        .matrix-grid__column.matrix-grid__head--preview { border-top: 2px dashed var(--accent); }
      `}</style>
    </div>
  );
}
