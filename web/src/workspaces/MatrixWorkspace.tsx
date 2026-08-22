import { useEffect, useMemo, useState } from "react";
import type { AnalysisBasis } from "../api/types";
import MatrixSidebar from "../components/matrix/MatrixSidebar";
import MatrixStage from "../features/matrix/MatrixStage";
import { boundedPins, PIN_STORAGE_KEY, storedSeeded, useMatrixRouteState } from "../features/matrix/routeState";
import { matrixVocabulary } from "../features/matrix/selectors";
import { useMatrixBasis } from "../features/matrix/useMatrixBasis";
import { useMatrixFrame } from "../features/matrix/useMatrixFrame";
import { useMatrixVocabulary } from "../features/matrix/useMatrixVocabulary";
import { matrixMuSourceForVal, matrixValueModeForVal, type MatrixSelection } from "../lib/matrix";
import { formatCT } from "../lib/time";
import "../features/matrix/matrixWorkspace.css";

interface Props { timestamp: Date | null; routeSearch: string; onSelectionRouteChange: (search: string) => void; onNavigateToMap: (search: string) => void; }

export default function MatrixWorkspace({ timestamp, routeSearch, onSelectionRouteChange, onNavigateToMap }: Props) {
  const { state, update } = useMatrixRouteState(routeSearch, onSelectionRouteChange);
  const [mobileIndexOpen, setMobileIndexOpen] = useState(false);
  const [seeded, setSeeded] = useState(storedSeeded);
  const { frame, loading, error, retry } = useMatrixFrame(timestamp, state, seeded);
  const { constraints, settlementPoints } = useMatrixVocabulary(frame);
  const vocabulary = useMemo(() => matrixVocabulary(constraints, settlementPoints, state), [constraints, settlementPoints, state]);
  const showBasis = state.tab === "nodes" && state.lens === "basis";
  const basisType: AnalysisBasis = state.val === "dmu" ? "realized" : "predicted";
  const basis = useMatrixBasis(showBasis, state.basisA, state.basisB, timestamp, frame, basisType);
  const [frameTopKey, setFrameTopKey] = useState<string | null>(null);
  useEffect(() => {
    if (!seeded && !state.pinnedConstraints.length && !state.pinnedSettlementPoints.length && frame?.available && (frame.rows.length || frame.columns.length)) {
      setSeeded(true);
      update({ pinnedConstraints: boundedPins(frame.rows.map((row) => row.constraint_key)), pinnedSettlementPoints: boundedPins(frame.columns.map((column) => column.settlement_point)) });
    }
  }, [frame, seeded, state.pinnedConstraints.length, state.pinnedSettlementPoints.length, update]);
  useEffect(() => { try { window.localStorage.setItem(PIN_STORAGE_KEY, JSON.stringify({ version: 1, seeded, constraints: state.pinnedConstraints, settlementPoints: state.pinnedSettlementPoints })); } catch { /* optional */ } }, [seeded, state.pinnedConstraints, state.pinnedSettlementPoints]);
  const selectionKey = state.selection?.kind === "constraint" ? state.selection.key : state.selection?.kind === "node" ? state.selection.point : null;
  const selectionInFrame = Boolean(selectionKey && (state.tab === "nodes" ? frame?.columns.some((column) => column.settlement_point === selectionKey) : frame?.rows.some((row) => row.constraint_key === selectionKey)));
  useEffect(() => { if (selectionInFrame && selectionKey) setFrameTopKey(selectionKey); }, [selectionInFrame, selectionKey]);
  const isPinned = (value: string, kind: "constraint" | "sp") => (kind === "constraint" ? state.pinnedConstraints : state.pinnedSettlementPoints).includes(value);
  const topRowKey = selectionInFrame ? selectionKey : frameTopKey;
  const previewKey = topRowKey && !isPinned(topRowKey, state.tab === "nodes" ? "sp" : "constraint") ? topRowKey : null;
  const selection = state.selection ?? (vocabulary.fullItems[0] ? state.tab === "nodes" ? { kind: "node" as const, point: vocabulary.fullItems[0].id } : { kind: "constraint" as const, key: vocabulary.fullItems[0].id } : null);
  const selectedId = selection?.kind === "constraint" ? selection.key : selection?.kind === "node" ? selection.point : null;
  const selectedConstraint = selection?.kind === "constraint" && constraints?.available ? constraints.rows?.find((row) => row.constraint_key === selection.key) ?? null : null;
  const selectedNode = selection?.kind === "node" ? vocabulary.nodeMeta.get(selection.point) ?? null : null;
  const usable = Boolean(frame?.available && frame.rows.length && frame.columns.length);
  const togglePin = (value: string, kind: "constraint" | "sp") => { const key = kind === "constraint" ? "pinnedConstraints" : "pinnedSettlementPoints"; const values = state[key]; update({ [key]: isPinned(value, kind) ? values.filter((item) => item !== value) : boundedPins([value, ...values]) }); };
  const select = (id: string) => { if (showBasis) { update(state.basisActiveSlot === "a" ? { basisA: id, basisActiveSlot: "b" } : { basisB: id, basisActiveSlot: "a" }); return; } update({ selection: state.tab === "nodes" ? { kind: "node", point: id } : { kind: "constraint", key: id } }); };
  const gridSelect = (next: MatrixSelection) => { if (next) update({ selection: next.kind === "constraint" ? { kind: "constraint", key: next.constraintKey } : { kind: "node", point: next.settlementPoint } }); };
  const reset = () => { setSeeded(false); update({ query: "", fType: "", fZone: "", selection: null, pinnedConstraints: [], pinnedSettlementPoints: [] }); };
  return <main className="matrix-workspace" aria-labelledby="matrix-title">
    <div className="matrix-workspace__heading"><span className="label">Explorer / matrix</span><h1 id="matrix-title">Constraint × settlement point</h1><p>{timestamp ? `${formatCT(timestamp, "MMM d, yyyy HH:mm")} CT` : "Waiting for playback data"}</p></div>
    {loading && !frame && !error && <div className="matrix-workspace__loading" role="status">Loading matrix frame…</div>}
    {error && <section className="matrix-workspace__state" role="alert"><h2>Unable to load Matrix</h2><p>{error}</p><button type="button" onClick={retry}>Retry</button></section>}
    {!error && frame && !frame.available && <section className="matrix-workspace__state" role="status"><h2>Matrix unavailable for this hour</h2><p>{frame.unavailable_reason === "artifact_missing" ? "No causal daily Matrix artifact was published for this delivery day." : "This timestamp is outside the available Matrix artifact."}</p></section>}
    {!error && frame?.available && !usable && <section className="matrix-workspace__state" role="status"><h2>No bounded Matrix values</h2><p>The selected artifact contains no rows or settlement-point columns for this bounded view.</p></section>}
    {!error && usable && frame && <div className="matrix-workspace__body"><MatrixSidebar tab={state.tab} items={vocabulary.filteredItems} totalCount={vocabulary.fullItems.length} selectedId={showBasis ? null : selectedId} basisSlots={showBasis ? { a: state.basisA, b: state.basisB } : undefined} onSelect={(id) => { select(id); setMobileIndexOpen(false); }} onTab={(tab) => update(tab === "constraints" && state.lens === "basis" ? { tab, lens: "read" } : { tab })} query={state.query} onQuery={(query) => update({ query })} onSearchFocus={() => setMobileIndexOpen(true)} fType={state.fType} fZone={state.fZone} typeOptions={vocabulary.typeOptions} zoneOptions={vocabulary.zoneOptions} onFilter={update} onTogglePin={(id) => togglePin(id, state.tab === "constraints" ? "constraint" : "sp")} onReset={reset} collapsed={!mobileIndexOpen} onToggleCollapsed={() => setMobileIndexOpen((open) => !open)} />
      <MatrixStage frame={frame} loading={loading} state={state} update={update} selection={selection} selectedConstraint={selectedConstraint} selectedNode={selectedNode} topRowKey={topRowKey} previewKey={previewKey} valueMode={matrixValueModeForVal(state.val)} muSource={matrixMuSourceForVal(state.val)} onGridSelect={gridSelect} isPinned={isPinned} onTogglePin={togglePin} basis={basis} basisType={basisType} timestamp={timestamp} onNavigateToMap={onNavigateToMap} /></div>}
    {!timestamp && !loading && <section className="matrix-workspace__state" role="status"><h2>Waiting for a playback hour</h2><p>Choose an available timestamp in the shared playback scrubber to load its Matrix frame.</p></section>}
  </main>;
}
