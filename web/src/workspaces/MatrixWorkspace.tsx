import { useEffect, useMemo, useRef, useState } from "react";
import type { AnalysisConstraintsResponse, AnalysisSettlementPointsResponse, MatrixFrame } from "../api/types";
import { getMatrixFrame } from "../api/matrixFrames";
import { fetchAnalysisConstraints, fetchAnalysisSettlementPoints, fetchTopology } from "../api/client";
import MatrixGrid from "../components/matrix/MatrixGrid";
import MatrixLegend from "../components/matrix/MatrixLegend";
import MatrixReadDetail from "../components/matrix/MatrixReadDetail";
import MatrixSidebar, { type MatrixSidebarItem } from "../components/matrix/MatrixSidebar";
import {
  matrixMuSourceForVal,
  matrixValueModeForVal,
  type MatrixEntitySelection,
  type MatrixLens,
  type MatrixSelection,
  type MatrixTab,
  type MatrixValTab,
} from "../lib/matrix";
import { formatCT } from "../lib/time";

let rememberedTab: MatrixTab = "constraints";
let rememberedLens: MatrixLens = "read";
let rememberedVal: MatrixValTab = "sf";
let rememberedSelection: MatrixEntitySelection = null;
let rememberedFrame: MatrixFrame | null = null;

const PIN_STORAGE_KEY = "ercotstress.matrix-pins.v1";
const MAX_PINS = 20;

function boundedPins(values: string[]) {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))].slice(0, MAX_PINS);
}

function storedPins(): { pinnedConstraints: string[]; pinnedSettlementPoints: string[] } {
  try {
    const value = JSON.parse(window.localStorage.getItem(PIN_STORAGE_KEY) ?? "null") as { version?: number; constraints?: string[]; settlementPoints?: string[] } | null;
    if (value?.version === 1) return {
      pinnedConstraints: boundedPins(value.constraints ?? []),
      pinnedSettlementPoints: boundedPins(value.settlementPoints ?? []),
    };
  } catch {
    // A malformed old value is recoverable through Reset.
  }
  return { pinnedConstraints: [], pinnedSettlementPoints: [] };
}

interface WorkspaceState {
  tab: MatrixTab;
  lens: MatrixLens;
  val: MatrixValTab;
  query: string;
  fType: string;
  fZone: string;
  selection: MatrixEntitySelection;
  pinnedConstraints: string[];
  pinnedSettlementPoints: string[];
}

function stateFromSearch(search: string): WorkspaceState {
  const params = new URLSearchParams(search);
  const stored = storedPins();
  const constraintKey = params.get("constraint");
  const sp = params.get("sp");
  const tabParam = params.get("tab");
  const tab: MatrixTab = tabParam === "nodes" || tabParam === "constraints"
    ? tabParam
    : sp && !constraintKey ? "nodes" : "constraints";
  const lensParam = params.get("lens");
  const valParam = params.get("val");
  return {
    tab,
    lens: lensParam === "sf" ? "sf" : "read",
    val: valParam === "fmu" || valParam === "dmu" ? valParam : "sf",
    query: (params.get("q") ?? params.get("constraint_search") ?? "").slice(0, 64),
    fType: params.get("type") ?? "",
    fZone: params.get("zone") ?? "",
    selection: constraintKey ? { kind: "constraint", key: constraintKey } : sp ? { kind: "node", point: sp } : null,
    pinnedConstraints: params.has("pinned_constraint") ? boundedPins(params.getAll("pinned_constraint")) : stored.pinnedConstraints,
    pinnedSettlementPoints: params.has("pinned_sp") ? boundedPins(params.getAll("pinned_sp")) : stored.pinnedSettlementPoints,
  };
}

function searchFromState(state: WorkspaceState): string {
  const params = new URLSearchParams();
  if (state.tab !== "constraints") params.set("tab", state.tab);
  if (state.lens !== "read") params.set("lens", state.lens);
  if (state.val !== "sf") params.set("val", state.val);
  if (state.query) params.set("q", state.query);
  if (state.fType) params.set("type", state.fType);
  if (state.fZone) params.set("zone", state.fZone);
  state.pinnedConstraints.forEach((key) => params.append("pinned_constraint", key));
  state.pinnedSettlementPoints.forEach((point) => params.append("pinned_sp", point));
  if (state.selection?.kind === "constraint") params.set("constraint", state.selection.key);
  if (state.selection?.kind === "node") params.set("sp", state.selection.point);
  const query = params.toString();
  return query ? `?${query}` : "";
}

interface Props {
  timestamp: Date | null;
  routeSearch: string;
  onSelectionRouteChange: (search: string) => void;
  onNavigateToMap: (search: string) => void;
}

function moneyLabel(value: number): string {
  return `$${Math.round(value).toLocaleString()}`;
}

export default function MatrixWorkspace({ timestamp, routeSearch, onSelectionRouteChange, onNavigateToMap }: Props) {
  const [frame, setFrame] = useState<MatrixFrame | null>(() =>
    rememberedFrame?.interval_ts === timestamp?.toISOString() ? rememberedFrame : null
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [requestVersion, setRequestVersion] = useState(0);
  const [state, setState] = useState<WorkspaceState>(() => {
    const params = new URLSearchParams(routeSearch);
    const fromRoute = stateFromSearch(routeSearch);
    return {
      ...fromRoute,
      tab: params.has("tab") || params.has("sp") || params.has("constraint") ? fromRoute.tab : rememberedTab,
      lens: params.has("lens") ? fromRoute.lens : rememberedLens,
      val: params.has("val") ? fromRoute.val : rememberedVal,
      selection: fromRoute.selection ?? rememberedSelection,
    };
  });
  const [constraintsResp, setConstraintsResp] = useState<AnalysisConstraintsResponse | null>(null);
  const [nodeMeta, setNodeMeta] = useState<Map<string, { type: string | null; zone: string | null }>>(new Map());
  const [settlementPointsResp, setSettlementPointsResp] = useState<AnalysisSettlementPointsResponse | null>(null);
  const requestId = useRef(0);

  useEffect(() => {
    if (!timestamp) return;
    const controller = new AbortController();
    const id = ++requestId.current;
    setLoading(true);
    setError(null);
    void getMatrixFrame(timestamp, {
      rowPreset: "top30",
      columnSet: "core_pinned",
      pinnedConstraints: state.pinnedConstraints,
      pinnedSettlementPoints: state.pinnedSettlementPoints,
    }, controller.signal)
      .then((nextFrame) => {
        if (id === requestId.current) {
          rememberedFrame = nextFrame;
          setFrame(nextFrame);
        }
      })
      .catch((requestError: unknown) => {
        if (requestError instanceof Error && requestError.name === "AbortError") return;
        if (id === requestId.current) {
          setError("The Matrix frame could not be loaded. Check the connection and retry.");
        }
      })
      .finally(() => {
        if (id === requestId.current) setLoading(false);
      });
    return () => controller.abort();
  }, [state.pinnedConstraints, state.pinnedSettlementPoints, requestVersion, timestamp]);

  // The topology's sp_type/load_zone properties are the only source of node
  // type/zone metadata — /analysis/settlement-points is deliberately a bare
  // vocabulary list. Fetched once; it does not vary with the current run.
  useEffect(() => {
    let cancelled = false;
    void fetchTopology()
      .then((topology) => {
        if (cancelled) return;
        const collection = (topology as { settlement_points?: { features?: Array<{ properties?: Record<string, unknown> }> } }).settlement_points;
        const next = new Map<string, { type: string | null; zone: string | null }>();
        for (const feature of collection?.features ?? []) {
          const props = feature.properties ?? {};
          const spId = props.sp_id;
          if (typeof spId !== "string") continue;
          next.set(spId, {
            type: typeof props.sp_type === "string" ? props.sp_type : null,
            zone: typeof props.load_zone === "string" ? props.load_zone : null,
          });
        }
        setNodeMeta(next);
      })
      .catch(() => { /* Node type/zone filters degrade to empty, not an error. */ });
    return () => { cancelled = true; };
  }, []);

  // The sidebar's full vocabulary depends on which day's artifact the frame
  // resolved to, so it follows the frame rather than the raw timestamp.
  useEffect(() => {
    if (!frame?.available) { setConstraintsResp(null); setSettlementPointsResp(null); return; }
    let cancelled = false;
    void fetchAnalysisConstraints(frame.delivery_date, { runId: frame.run_id })
      .then((response) => { if (!cancelled) setConstraintsResp(response); })
      .catch(() => { if (!cancelled) setConstraintsResp(null); });
    void fetchAnalysisSettlementPoints(frame.delivery_date, { runId: frame.run_id })
      .then((response) => { if (!cancelled) setSettlementPointsResp(response); })
      .catch(() => { if (!cancelled) setSettlementPointsResp(null); });
    return () => { cancelled = true; };
  }, [frame?.delivery_date, frame?.run_id, frame?.available]);

  useEffect(() => {
    try {
      window.localStorage.setItem(PIN_STORAGE_KEY, JSON.stringify({
        version: 1, constraints: state.pinnedConstraints, settlementPoints: state.pinnedSettlementPoints,
      }));
    } catch {
      // Local persistence is deliberately optional; URL state remains usable.
    }
  }, [state.pinnedConstraints, state.pinnedSettlementPoints]);

  const update = (patch: Partial<WorkspaceState>) => {
    setState((current) => {
      const next = { ...current, ...patch };
      rememberedTab = next.tab; rememberedLens = next.lens; rememberedVal = next.val;
      rememberedSelection = next.selection;
      onSelectionRouteChange(searchFromState(next));
      return next;
    });
  };

  const damPending = frame?.dam_status === "pending";
  useEffect(() => {
    if (state.val === "dmu" && damPending) update({ val: "fmu" });
    // `update` is stable across renders; including it would fire on every
    // selection/filter change, not just the DAM-availability flip this
    // effect exists to react to.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [damPending]);

  // Selection and filter state are URL-addressable. A hidden selection
  // remains explicit instead of being erased when a filter changes its frame.
  useEffect(() => {
    const next = stateFromSearch(routeSearch);
    rememberedTab = next.tab; rememberedLens = next.lens; rememberedVal = next.val;
    rememberedSelection = next.selection;
    setState(next);
  }, [routeSearch]);

  const isPinned = (value: string, kind: "constraint" | "sp") =>
    (kind === "constraint" ? state.pinnedConstraints : state.pinnedSettlementPoints).includes(value);
  const togglePin = (value: string, kind: "constraint" | "sp") => {
    const key = kind === "constraint" ? "pinnedConstraints" : "pinnedSettlementPoints";
    const values = state[key];
    update({ [key]: isPinned(value, kind) ? values.filter((item) => item !== value) : boundedPins([...values, value]) });
  };

  const constraintItems = useMemo<MatrixSidebarItem[]>(() => {
    const rows = constraintsResp?.available ? constraintsResp.rows ?? [] : [];
    return [...rows]
      .sort((a, b) => a.daily_mu_rank - b.daily_mu_rank)
      .map((row) => ({
        id: row.constraint_key,
        label: row.name,
        sub: row.contingency,
        type: row.ctype,
        zone: row.zone,
        sizeLabel: moneyLabel(row.daily_mu_sum),
        pinned: isPinned(row.constraint_key, "constraint"),
      }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [constraintsResp, state.pinnedConstraints]);

  const nodeItems = useMemo<MatrixSidebarItem[]>(() => {
    const points = settlementPointsResp?.available ? settlementPointsResp.settlement_points ?? [] : [];
    return [...points].sort((a, b) => a.localeCompare(b)).map((point) => {
      const meta = nodeMeta.get(point);
      return {
        id: point,
        label: point,
        sub: null,
        type: meta?.type ?? null,
        zone: meta?.zone ?? null,
        sizeLabel: null,
        pinned: isPinned(point, "sp"),
      };
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settlementPointsResp, nodeMeta, state.pinnedSettlementPoints]);

  const fullItems = state.tab === "constraints" ? constraintItems : nodeItems;
  const typeOptions = useMemo(
    () => [...new Set(fullItems.map((item) => item.type).filter((t): t is string => Boolean(t)))].sort(),
    [fullItems]
  );
  const zoneOptions = useMemo(
    () => [...new Set(fullItems.map((item) => item.zone).filter((z): z is string => Boolean(z)))].sort(),
    [fullItems]
  );
  const filteredItems = useMemo(() => {
    const q = state.query.trim().toLowerCase();
    return fullItems.filter((item) => {
      if (state.fType && item.type !== state.fType) return false;
      if (state.fZone && item.zone !== state.fZone) return false;
      if (q) {
        const haystack = `${item.id} ${item.label} ${item.sub ?? ""}`.toLowerCase();
        if (!haystack.includes(q)) return false;
      }
      return true;
    });
  }, [fullItems, state.query, state.fType, state.fZone]);

  const effectiveSelection: MatrixEntitySelection = state.selection ?? (fullItems.length
    ? (state.tab === "constraints" ? { kind: "constraint", key: fullItems[0].id } : { kind: "node", point: fullItems[0].id })
    : null);

  const selectedIdForSidebar = state.tab === "constraints"
    ? (effectiveSelection?.kind === "constraint" ? effectiveSelection.key : null)
    : (effectiveSelection?.kind === "node" ? effectiveSelection.point : null);

  const selectedConstraintRow = effectiveSelection?.kind === "constraint"
    ? constraintsResp?.available ? constraintsResp.rows?.find((row) => row.constraint_key === effectiveSelection.key) ?? null : null
    : null;
  const selectedNodeMeta = effectiveSelection?.kind === "node" ? nodeMeta.get(effectiveSelection.point) ?? null : null;

  const selectId = (id: string) => update({
    selection: state.tab === "constraints" ? { kind: "constraint", key: id } : { kind: "node", point: id },
  });
  const handleGridSelect = (gridSelection: MatrixSelection) => {
    if (!gridSelection) return;
    if (gridSelection.kind === "constraint") { update({ selection: { kind: "constraint", key: gridSelection.constraintKey } }); return; }
    if (gridSelection.kind === "settlementPoint") { update({ selection: { kind: "node", point: gridSelection.settlementPoint } }); return; }
    update({ selection: state.tab === "nodes" ? { kind: "node", point: gridSelection.settlementPoint } : { kind: "constraint", key: gridSelection.constraintKey } });
  };
  const resetView = () => {
    try { window.localStorage.removeItem(PIN_STORAGE_KEY); } catch { /* Reset still works in memory. */ }
    update({ query: "", fType: "", fZone: "", selection: null, pinnedConstraints: [], pinnedSettlementPoints: [] });
  };

  const valueMode = matrixValueModeForVal(state.val);
  const muSource = matrixMuSourceForVal(state.val);
  const legendMax = frame?.available
    ? (valueMode === "sf" ? frame.sf_day_max_abs : frame.contribution_day_max_abs)
    : 0;

  const gridSelection: MatrixSelection = effectiveSelection?.kind === "constraint"
    ? { kind: "constraint", constraintKey: effectiveSelection.key }
    : effectiveSelection?.kind === "node"
      ? { kind: "settlementPoint", settlementPoint: effectiveSelection.point }
      : null;

  const isUsable = frame?.available && frame.rows.length > 0 && frame.columns.length > 0;
  const isUnavailable = frame && !frame.available;
  const isEmpty = frame?.available && !isUsable;
  const damUnmatchedRows = frame?.rows.filter((row) => row.ercot_dam_mu == null).length ?? 0;

  const selectedRowVisible = !effectiveSelection || effectiveSelection.kind === "node" || Boolean(frame?.rows.some((row) => row.constraint_key === effectiveSelection.key));
  const selectedColumnVisible = !effectiveSelection || effectiveSelection.kind === "constraint" || Boolean(frame?.columns.some((column) => column.settlement_point === effectiveSelection.point));
  const selectionHidden = Boolean(effectiveSelection && frame?.available && (!selectedRowVisible || !selectedColumnVisible));
  const revealSelection = () => {
    if (!effectiveSelection) return;
    if (effectiveSelection.kind === "constraint") togglePin(effectiveSelection.key, "constraint");
    else togglePin(effectiveSelection.point, "sp");
  };

  return (
    <main className="matrix-workspace" aria-labelledby="matrix-title">
      <div className="matrix-workspace__heading">
        <span className="label">Explorer / matrix</span>
        <h1 id="matrix-title">Constraint × settlement point</h1>
        <p>{timestamp ? `${formatCT(timestamp, "MMM d, yyyy HH:mm")} CT` : "Waiting for playback data"}</p>
      </div>

      {loading && !frame && !error && <div className="matrix-workspace__loading" role="status">Loading matrix frame…</div>}
      {error && (
        <section className="matrix-workspace__state" role="alert">
          <h2>Unable to load Matrix</h2>
          <p>{error}</p>
          <button type="button" onClick={() => setRequestVersion((version) => version + 1)}>Retry</button>
        </section>
      )}
      {!error && isUnavailable && frame && (
        <section className="matrix-workspace__state" role="status">
          <h2>Matrix unavailable for this hour</h2>
          <p>{frame.unavailable_reason === "artifact_missing" ? "No causal daily Matrix artifact was published for this delivery day." : "This timestamp is outside the available Matrix artifact."}</p>
        </section>
      )}
      {!error && isEmpty && (
        <section className="matrix-workspace__state" role="status">
          <h2>No bounded Matrix values</h2>
          <p>The selected artifact contains no rows or settlement-point columns for this bounded view.</p>
        </section>
      )}

      {!error && isUsable && frame && (
        <div className="matrix-workspace__body">
          <MatrixSidebar
            tab={state.tab}
            items={filteredItems}
            totalCount={fullItems.length}
            selectedId={selectedIdForSidebar}
            onSelect={selectId}
            onTab={(tab) => update({ tab })}
            query={state.query}
            onQuery={(query) => update({ query })}
            fType={state.fType}
            fZone={state.fZone}
            typeOptions={typeOptions}
            zoneOptions={zoneOptions}
            onFilter={(next) => update(next)}
            onTogglePin={(id) => togglePin(id, state.tab === "constraints" ? "constraint" : "sp")}
            onReset={resetView}
          />
          <section className="matrix-workspace__stage" aria-busy={loading}>
            <header className="matrix-workspace__stage-header">
              <div className="matrix-workspace__toggle" role="tablist" aria-label="Lens">
                <button type="button" role="tab" aria-selected={state.lens === "read"} className={state.lens === "read" ? "is-active" : ""} onClick={() => update({ lens: "read" })}>Read</button>
                <button type="button" role="tab" aria-selected={state.lens === "sf"} className={state.lens === "sf" ? "is-active" : ""} onClick={() => update({ lens: "sf" })}>SF</button>
              </div>
              {state.lens === "sf" && (
                <div className="matrix-workspace__toggle" role="tablist" aria-label="Value">
                  <button type="button" className={state.val === "sf" ? "is-active" : ""} onClick={() => update({ val: "sf" })}>Shift Factor</button>
                  <button type="button" className={state.val === "fmu" ? "is-active" : ""} onClick={() => update({ val: "fmu" })}>Forecast μ</button>
                  <button type="button" disabled={damPending} title={damPending ? "ERCOT DAM μ has not been published for this hour" : undefined} className={state.val === "dmu" ? "is-active" : ""} onClick={() => update({ val: "dmu" })}>ERCOT DAM μ</button>
                </div>
              )}
              {state.lens === "sf" && <MatrixLegend mode={valueMode} maxAbs={legendMax} />}
            </header>

            {state.lens === "read" && (
              <div className="matrix-workspace__read">
                <MatrixReadDetail
                  selection={effectiveSelection}
                  timestamp={timestamp}
                  val={state.val}
                  deliveryDate={frame.delivery_date}
                  runId={frame.run_id}
                  damStatus={frame.dam_status}
                  constraintRow={selectedConstraintRow}
                  nodeMeta={selectedNodeMeta}
                  onNavigateToMap={onNavigateToMap}
                />
              </div>
            )}

            {state.lens === "sf" && (
              <>
                <div className="matrix-workspace__meta">
                  <span>Run {frame.run_id}</span>
                  <span>Delivery day {frame.delivery_date}</span>
                  <span>{frame.rows.length} of {frame.total_constraint_count} constraints</span>
                  <span>{frame.columns.length} of {frame.total_settlement_point_count} settlement points</span>
                  {loading && <span>Updating frame…</span>}
                </div>
                <div className={`matrix-workspace__notices${selectionHidden || (valueMode === "contribution" && frame.dam_status !== "available") ? " has-notices" : ""}`}>
                  {selectionHidden && <div className="matrix-workspace__notice" role="status">The selected item is hidden by the current view. <button type="button" onClick={revealSelection}>Pin it</button></div>}
                  {valueMode === "contribution" && frame.dam_status === "pending" && (
                    <div className="matrix-workspace__notice" role="status">ERCOT DAM μ is pending; Contribution uses Forecast μ.</div>
                  )}
                  {valueMode === "contribution" && frame.dam_status === "partial" && (
                    <div className="matrix-workspace__notice" role="status">DAM μ: {frame.rows.length - damUnmatchedRows}/{frame.rows.length} constraints matched; unmatched cells are unavailable.</div>
                  )}
                </div>
                <MatrixGrid frame={frame} mode={valueMode} muSource={muSource} selection={gridSelection} maxAbs={legendMax} onSelect={handleGridSelect} />
              </>
            )}
          </section>
        </div>
      )}

      {!timestamp && !loading && (
        <section className="matrix-workspace__state" role="status">
          <h2>Waiting for a playback hour</h2>
          <p>Choose an available timestamp in the shared playback scrubber to load its Matrix frame.</p>
        </section>
      )}

      <style>{`
        .matrix-workspace { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; padding: 16px; gap: 12px; background: var(--bg-base); }
        .matrix-workspace__heading { min-width: 0; flex: 0 0 auto; }
        .matrix-workspace h1 { margin: 3px 0; font: 600 var(--fs-xl)/1.2 var(--font-label); color: var(--text-primary); }
        .matrix-workspace p { color: var(--text-secondary); font-size: var(--fs-label); margin: 0; }
        .matrix-workspace button { border: 0; background: transparent; color: var(--text-secondary); cursor: pointer; font: 500 var(--fs-label) var(--font-sans); padding: 6px 8px; }
        .matrix-workspace__toggle { display: flex; gap: 7px; }
        .matrix-workspace__toggle button { background: var(--bg-surface); border: 1px solid var(--border); color: var(--text-secondary); font-weight: 600; padding: 7px 11px; }
        .matrix-workspace__toggle button.is-active { background: var(--accent-dim); border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); color: var(--accent); }
        .matrix-workspace button:disabled { cursor: not-allowed; color: var(--text-muted); }
        .matrix-workspace__loading { display: grid; flex: 1; place-items: center; color: var(--text-secondary); }
        .matrix-workspace__state { align-self: center; background: var(--bg-panel); border: 1px solid var(--border); box-shadow: var(--shadow-panel); max-width: 500px; padding: 22px; width: min(500px, 100%); }
        .matrix-workspace__state h2 { font: 600 var(--fs-lg) var(--font-label); margin: 0 0 8px; }
        .matrix-workspace__state p { line-height: 1.45; }
        .matrix-workspace__state button { background: var(--accent-dim); color: var(--accent); margin-top: 14px; }
        .matrix-workspace__body { display: flex; flex: 1; min-height: 0; gap: 0; }
        .matrix-workspace__stage { display: flex; flex-direction: column; flex: 1; min-height: 0; min-width: 0; border: 1px solid var(--border); background: var(--bg-panel); overflow: hidden; }
        .matrix-workspace__stage-header { align-items: center; border-bottom: 1px solid var(--border); display: flex; flex-wrap: wrap; gap: 12px; padding: 8px 10px; }
        .matrix-workspace__read { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 4px 18px 18px; }
        .matrix-workspace__meta { color: var(--text-secondary); display: flex; flex-wrap: wrap; font-size: var(--fs-label); gap: 12px; padding: 8px 10px; border-bottom: 1px solid var(--border); }
        .matrix-workspace__notices { min-height: 0; }
        .matrix-workspace__notices.has-notices { border-bottom: 1px solid var(--border); display: grid; gap: 1px; }
        .matrix-workspace__notice { background: var(--accent-dim); color: var(--text-secondary); font-size: var(--fs-label); padding: 5px 10px; }
        .matrix-legend { flex: 0 0 240px; width: 240px; margin-left: auto; }
        .matrix-legend__title { color: var(--text-secondary); margin-bottom: 4px; }
        .matrix-legend__bar { height: 8px; }
        .matrix-legend__ticks, .matrix-legend__signs { display: flex; justify-content: space-between; font-size: 9px; margin-top: 3px; }
        .matrix-legend__signs { color: var(--text-secondary); }
        .matrix-grid { overflow: auto; min-height: 0; flex: 1; outline: none; }
        .matrix-grid:focus-visible, .matrix-grid [tabindex="0"]:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; position: relative; z-index: 3; }
        .matrix-grid table { border-collapse: separate; border-spacing: 0; font-size: var(--fs-micro); width: max-content; }
        .matrix-grid th, .matrix-grid td { border-right: 1px solid color-mix(in srgb, var(--border) 70%, transparent); border-bottom: 1px solid color-mix(in srgb, var(--border) 70%, transparent); }
        .matrix-grid thead th { background: var(--bg-panel); position: sticky; top: 0; z-index: 2; height: 50px; vertical-align: bottom; }
        .matrix-grid__corner { left: 0; z-index: 4 !important; min-width: 205px; padding: 7px 10px; text-align: left; }
        .matrix-grid__corner span, .matrix-grid__row span { display: block; color: var(--text-primary); font-weight: 600; }
        .matrix-grid small { color: var(--text-secondary); display: block; font-size: 9px; font-weight: 400; margin-top: 2px; }
        .matrix-grid__column { min-width: 72px; max-width: 72px; cursor: pointer; padding: 6px; text-align: right; white-space: nowrap; }
        .matrix-grid__column > span { color: var(--text-primary); display: block; overflow: hidden; text-overflow: ellipsis; }
        .matrix-grid__row { background: var(--bg-panel); cursor: pointer; left: 0; min-width: 205px; max-width: 205px; padding: 6px 10px; position: sticky; text-align: left; z-index: 1; }
        .matrix-grid__row > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .matrix-grid__cell { color: #172033; cursor: pointer; font: 600 var(--fs-micro) var(--font-mono); min-width: 72px; padding: 7px 6px; text-align: right; white-space: nowrap; }
        .matrix-grid__cell--unavailable { color: var(--text-muted); background: repeating-linear-gradient(-45deg, var(--bg-surface), var(--bg-surface) 3px, var(--bg-panel) 3px, var(--bg-panel) 6px) !important; }
        .matrix-grid__column[aria-selected="true"] { background: color-mix(in srgb, var(--accent-dim) 72%, var(--bg-panel)); box-shadow: inset 0 -3px var(--accent); }
        .matrix-grid__row[aria-selected="true"] { background: color-mix(in srgb, var(--accent-dim) 72%, var(--bg-panel)); box-shadow: inset 3px 0 var(--accent); }
        .matrix-grid__cell.is-selected { box-shadow: inset 0 0 0 3px var(--accent); position: relative; z-index: 1; }
        @media (max-width: 767px) { .matrix-workspace { padding: 10px; } .matrix-workspace__body { flex-direction: column; } .matrix-grid__corner, .matrix-grid__row { min-width: 155px; max-width: 155px; } .matrix-grid::before { color: var(--text-secondary); content: "Scroll horizontally to inspect settlement points"; display: block; font-size: var(--fs-micro); padding: 5px 8px; position: sticky; left: 0; } }
      `}</style>
    </main>
  );
}
