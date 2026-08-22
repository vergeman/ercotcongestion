/* eslint-disable react-hooks/set-state-in-effect */
import { useLayoutEffect, useState } from "react";
import type {
  AnalysisBasis,
  AnalysisConstraintRow,
  MatrixFrame,
} from "../../api/types";
import MatrixBasisPanel from "../../components/matrix/MatrixBasisPanel";
import MatrixGrid from "../../components/matrix/MatrixGrid";
import MatrixLegend, {
  MatrixReachLegend,
} from "../../components/matrix/MatrixLegend";
import MatrixReadDetail from "../../components/matrix/MatrixReadDetail";
import Tooltip from "../../components/ui/Tooltip";
import type {
  MatrixEntitySelection,
  MatrixMuSource,
  MatrixSelection,
  MatrixValueMode,
} from "../../lib/matrix";
import type { MatrixRouteState } from "./routeState";
import { MATRIX_COPY } from "./copy";
import type { useMatrixBasis } from "./useMatrixBasis";

interface Props {
  frame: MatrixFrame;
  loading: boolean;
  state: MatrixRouteState;
  update: (patch: Partial<MatrixRouteState>) => void;
  selection: MatrixEntitySelection;
  selectedConstraint: AnalysisConstraintRow | null;
  selectedNode: {
    type: string | null;
    zone: string | null;
    lat: number | null;
    lon: number | null;
  } | null;
  topRowKey: string | null;
  previewKey: string | null;
  valueMode: MatrixValueMode;
  muSource: MatrixMuSource;
  onGridSelect: (selection: MatrixSelection) => void;
  isPinned: (value: string, kind: "constraint" | "sp") => boolean;
  onTogglePin: (value: string, kind: "constraint" | "sp") => void;
  basis: ReturnType<typeof useMatrixBasis>;
  basisType: AnalysisBasis;
  timestamp: Date | null;
  onNavigateToMap: (search: string) => void;
}

export default function MatrixStage({
  frame,
  loading,
  state,
  update,
  selection,
  selectedConstraint,
  selectedNode,
  topRowKey,
  previewKey,
  valueMode,
  muSource,
  onGridSelect,
  isPinned,
  onTogglePin,
  basis,
  basisType,
  timestamp,
  onNavigateToMap,
}: Props) {
  const detailKey = selection
    ? `${selection.kind}:${
        selection.kind === "constraint" ? selection.key : selection.point
      }:${state.val}`
    : "empty";
  const [detailLoading, setDetailLoading] = useState(true);
  useLayoutEffect(() => {
    setDetailLoading(true);
    const timer = window.setTimeout(() => setDetailLoading(false), 220);
    return () => window.clearTimeout(timer);
  }, [detailKey]);
  const gridSelection: MatrixSelection =
    state.selection?.kind === "constraint"
      ? { kind: "constraint", constraintKey: state.selection.key }
      : state.selection?.kind === "node"
      ? { kind: "settlementPoint", settlementPoint: state.selection.point }
      : null;
  const damUnmatchedRows = frame.rows.filter(
    (row) => row.ercot_dam_mu == null
  ).length;
  return (
    <section className="matrix-workspace__stage" aria-busy={loading}>
      <header className="matrix-workspace__stage-header">
        <div
          className="matrix-workspace__toggle"
          role="tablist"
          aria-label={MATRIX_COPY.lens.label}
        >
          <button
            type="button"
            role="tab"
            aria-selected={state.lens === "read"}
            className={state.lens === "read" ? "is-active" : ""}
            onClick={() => update({ lens: "read" })}
          >
            {MATRIX_COPY.lens.detail}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={state.lens === "sf"}
            className={state.lens === "sf" ? "is-active" : ""}
            onClick={() => update({ lens: "sf" })}
          >
            {MATRIX_COPY.lens.sf}
          </button>
          {state.tab !== "nodes" ? (
            <Tooltip
              as="span"
              className="matrix-workspace__disabled-tab"
              tip={MATRIX_COPY.basisUnavailable}
            >
              <button type="button" role="tab" aria-selected={false} disabled>
                {MATRIX_COPY.lens.basis}
              </button>
            </Tooltip>
          ) : (
            <button
              type="button"
              role="tab"
              aria-selected={state.lens === "basis"}
              className={state.lens === "basis" ? "is-active" : ""}
              onClick={() => update({ lens: "basis" })}
            >
              {MATRIX_COPY.lens.basis}
            </button>
          )}
        </div>
        {state.lens === "sf" && (
          <div
            className="matrix-workspace__toggle matrix-workspace__toggle--data"
            role="group"
            aria-label={MATRIX_COPY.value.label}
          >
            <span className="label matrix-workspace__toggle-label">
              {MATRIX_COPY.value.data}
            </span>
            {(
              [
                ["sf", MATRIX_COPY.value.shiftFactor],
                ["fmu", MATRIX_COPY.value.forecastMu],
                ["dmu", MATRIX_COPY.value.damMu],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={state.val === value ? "is-active" : ""}
                onClick={() => update({ val: value })}
              >
                {label}
              </button>
            ))}
          </div>
        )}
        {state.lens === "basis" && (
          <div
            className="matrix-workspace__toggle matrix-workspace__toggle--data"
            role="group"
            aria-label={MATRIX_COPY.basisSource}
          >
            <span className="label matrix-workspace__toggle-label">
              {MATRIX_COPY.value.data}
            </span>
            <button
              type="button"
              className={state.val !== "dmu" ? "is-active" : ""}
              onClick={() => update({ val: "fmu" })}
            >
              {MATRIX_COPY.value.forecastMu}
            </button>
            <button
              type="button"
              className={state.val === "dmu" ? "is-active" : ""}
              onClick={() => update({ val: "dmu" })}
            >
              {MATRIX_COPY.value.damMu}
            </button>
          </div>
        )}
        {state.lens === "read" && <MatrixReachLegend />}
        {state.lens === "sf" && (
          <MatrixLegend
            mode={valueMode}
            maxAbs={
              valueMode === "sf"
                ? frame.sf_day_max_abs
                : frame.contribution_day_max_abs
            }
          />
        )}
      </header>
      {state.lens === "read" && (
        <div className="matrix-workspace__read matrix-workspace__read--loading">
          {detailLoading && (
            <div className="matrix-workspace__detail-loading" role="status">
              <span
                className="matrix-workspace__detail-spinner"
                aria-hidden="true"
              />
              <span>{MATRIX_COPY.loadingDetail}</span>
            </div>
          )}
          <MatrixReadDetail
            selection={selection}
            timestamp={timestamp}
            val={state.val}
            deliveryDate={frame.delivery_date}
            damStatus={frame.dam_status}
            constraintRow={selectedConstraint}
            nodeMeta={selectedNode}
            onNavigateToMap={onNavigateToMap}
          />
        </div>
      )}
      {state.lens === "sf" && (
        <>
          <div className="matrix-workspace__meta">
            <span>{MATRIX_COPY.run(frame.run_id)}</span>
            <span>{MATRIX_COPY.deliveryDay(frame.delivery_date)}</span>
            <span>
              {MATRIX_COPY.constraintCount(
                frame.rows.length,
                frame.total_constraint_count
              )}
            </span>
            <span>
              {MATRIX_COPY.settlementPointCount(
                frame.columns.length,
                frame.total_settlement_point_count
              )}
            </span>
            {loading && <span>{MATRIX_COPY.updatingFrame}</span>}
          </div>
          <div
            className={`matrix-workspace__notices${
              valueMode === "contribution" && frame.dam_status !== "available"
                ? " has-notices"
                : ""
            }`}
          >
            {valueMode === "contribution" && frame.dam_status === "pending" && (
              <div className="matrix-workspace__notice" role="status">
                {MATRIX_COPY.pendingDam}
              </div>
            )}
            {valueMode === "contribution" && frame.dam_status === "partial" && (
              <div className="matrix-workspace__notice" role="status">
                {MATRIX_COPY.partialDam(
                  frame.rows.length - damUnmatchedRows,
                  frame.rows.length
                )}
              </div>
            )}
          </div>
          <MatrixGrid
            frame={frame}
            orientation={state.tab === "nodes" ? "nodes" : "constraints"}
            topRowKey={topRowKey}
            previewKey={previewKey}
            mode={valueMode}
            muSource={muSource}
            selection={gridSelection}
            maxAbs={
              valueMode === "sf"
                ? frame.sf_day_max_abs
                : frame.contribution_day_max_abs
            }
            onSelect={onGridSelect}
            isPinned={(item) =>
              isPinned(
                item.key,
                item.kind === "constraint" ? "constraint" : "sp"
              )
            }
            onTogglePin={(item) =>
              onTogglePin(
                item.key,
                item.kind === "constraint" ? "constraint" : "sp"
              )
            }
          />
        </>
      )}
      {state.lens === "basis" && (
        <MatrixBasisPanel
          aNode={state.basisA}
          bNode={state.basisB}
          activeSlot={state.basisActiveSlot}
          loading={basis.loading}
          primary={basis.primary}
          realizedTotal={basisType === "predicted" ? basis.realizedTotal : null}
          settledBasis={basisType === "predicted" ? basis.realizedTotal : null}
          onTargetSlot={(basisActiveSlot) => update({ basisActiveSlot })}
          onSwap={() => update({ basisA: state.basisB, basisB: state.basisA })}
          onClear={(slot) =>
            update(
              slot === "a"
                ? { basisA: null, basisActiveSlot: "a" }
                : { basisB: null, basisActiveSlot: "b" }
            )
          }
        />
      )}
    </section>
  );
}
