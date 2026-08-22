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
          aria-label="Lens"
        >
          <button
            type="button"
            role="tab"
            aria-selected={state.lens === "read"}
            className={state.lens === "read" ? "is-active" : ""}
            onClick={() => update({ lens: "read" })}
          >
            Detail
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={state.lens === "sf"}
            className={state.lens === "sf" ? "is-active" : ""}
            onClick={() => update({ lens: "sf" })}
          >
            SF
          </button>
          {state.tab !== "nodes" ? (
            <Tooltip
              as="span"
              className="matrix-workspace__disabled-tab"
              tip="Basis is available only on the Nodes tab because it compares two settlement points."
            >
              <button type="button" role="tab" aria-selected={false} disabled>
                Basis
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
              Basis
            </button>
          )}
        </div>
        {state.lens === "sf" && (
          <div
            className="matrix-workspace__toggle matrix-workspace__toggle--data"
            role="group"
            aria-label="Value"
          >
            <span className="label matrix-workspace__toggle-label">Data</span>
            {(
              [
                ["sf", "Shift Factor"],
                ["fmu", "Forecast μ"],
                ["dmu", "ERCOT DAM μ"],
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
            aria-label="Basis μ source"
          >
            <span className="label matrix-workspace__toggle-label">Data</span>
            <button
              type="button"
              className={state.val !== "dmu" ? "is-active" : ""}
              onClick={() => update({ val: "fmu" })}
            >
              Forecast μ
            </button>
            <button
              type="button"
              className={state.val === "dmu" ? "is-active" : ""}
              onClick={() => update({ val: "dmu" })}
            >
              ERCOT DAM μ
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
        <div className="matrix-workspace__read">
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
            <span>Run {frame.run_id}</span>
            <span>Delivery day {frame.delivery_date}</span>
            <span>
              {frame.rows.length} of {frame.total_constraint_count} constraints
            </span>
            <span>
              {frame.columns.length} of {frame.total_settlement_point_count}{" "}
              settlement points
            </span>
            {loading && <span>Updating frame…</span>}
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
                No ERCOT DAM μ values matched the displayed constraints for this
                hour.
              </div>
            )}
            {valueMode === "contribution" && frame.dam_status === "partial" && (
              <div className="matrix-workspace__notice" role="status">
                DAM μ: {frame.rows.length - damUnmatchedRows}/
                {frame.rows.length} constraints matched; unmatched cells are
                unavailable.
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
