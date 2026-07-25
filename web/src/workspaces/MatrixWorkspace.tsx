import { useEffect, useRef, useState } from "react";
import type { MatrixFrame } from "../api/types";
import { getMatrixFrame } from "../api/matrixFrames";
import MatrixGrid from "../components/matrix/MatrixGrid";
import MatrixLegend from "../components/matrix/MatrixLegend";
import MatrixInspector from "../components/matrix/MatrixInspector";
import {
  type MatrixMuSource,
  type MatrixSelection,
  type MatrixValueMode,
} from "../lib/matrix";
import { formatCT } from "../lib/time";

let rememberedValueMode: MatrixValueMode = "sf";
let rememberedMuSource: MatrixMuSource = "forecast";
let rememberedInspectorCollapsed = true;
let rememberedSelection: MatrixSelection = null;
let rememberedFrame: MatrixFrame | null = null;

const PIN_STORAGE_KEY = "ercotstress.matrix-pins.v1";
const MAX_PINS = 20;

type RowPreset = "top30" | "top100" | "pinned";
type ColumnSet = "core" | "anchors" | "pinned" | "core_pinned";
type ConstraintType = "gtc" | "transmission" | "radial";

interface DiscoveryState {
  rowPreset: RowPreset;
  constraintType: ConstraintType | "";
  constraintSearch: string;
  settlementPointSearch: string;
  columnSet: ColumnSet;
  pinnedConstraints: string[];
  pinnedSettlementPoints: string[];
}

const DEFAULT_DISCOVERY: Omit<DiscoveryState, "pinnedConstraints" | "pinnedSettlementPoints"> = {
  rowPreset: "top30", constraintType: "", constraintSearch: "", settlementPointSearch: "", columnSet: "core",
};

function boundedPins(values: string[]) {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))].slice(0, MAX_PINS);
}

function storedPins(): Pick<DiscoveryState, "pinnedConstraints" | "pinnedSettlementPoints"> {
  try {
    const value = JSON.parse(window.localStorage.getItem(PIN_STORAGE_KEY) ?? "null") as { version?: number; constraints?: string[]; settlementPoints?: string[] } | null;
    if (value?.version === 1) return {
      pinnedConstraints: boundedPins(value.constraints ?? []),
      pinnedSettlementPoints: boundedPins(value.settlementPoints ?? []),
    };
  } catch {
    // A malformed old value is recoverable through Reset view.
  }
  return { pinnedConstraints: [], pinnedSettlementPoints: [] };
}

function discoveryFromSearch(search: string): DiscoveryState {
  const params = new URLSearchParams(search);
  const stored = storedPins();
  const rowPreset = params.get("rows");
  const columnSet = params.get("columns");
  const type = params.get("ctype");
  return {
    rowPreset: rowPreset === "top100" || rowPreset === "pinned" ? rowPreset : "top30",
    columnSet: columnSet === "anchors" || columnSet === "pinned" || columnSet === "core_pinned" ? columnSet : "core",
    constraintType: type === "gtc" || type === "transmission" || type === "radial" ? type : "",
    constraintSearch: params.get("constraint_search")?.slice(0, 64) ?? "",
    settlementPointSearch: params.get("sp_search")?.slice(0, 64) ?? "",
    pinnedConstraints: params.has("pinned_constraint") ? boundedPins(params.getAll("pinned_constraint")) : stored.pinnedConstraints,
    pinnedSettlementPoints: params.has("pinned_sp") ? boundedPins(params.getAll("pinned_sp")) : stored.pinnedSettlementPoints,
  };
}

interface Props {
  timestamp: Date | null;
  routeSearch: string;
  onSelectionRouteChange: (search: string) => void;
  onNavigateToMap: (search: string) => void;
}

function selectionFromSearch(search: string): MatrixSelection {
  const params = new URLSearchParams(search);
  const constraintKey = params.get("constraint");
  const settlementPoint = params.get("sp");
  if (constraintKey && settlementPoint) return { kind: "cell", constraintKey, settlementPoint };
  if (constraintKey) return { kind: "constraint", constraintKey };
  return settlementPoint ? { kind: "settlementPoint", settlementPoint } : null;
}

function matrixSearch(discovery: DiscoveryState, selection: MatrixSelection): string {
  const params = new URLSearchParams();
  if (discovery.rowPreset !== "top30") params.set("rows", discovery.rowPreset);
  if (discovery.columnSet !== "core") params.set("columns", discovery.columnSet);
  if (discovery.constraintType) params.set("ctype", discovery.constraintType);
  if (discovery.constraintSearch) params.set("constraint_search", discovery.constraintSearch);
  if (discovery.settlementPointSearch) params.set("sp_search", discovery.settlementPointSearch);
  discovery.pinnedConstraints.forEach((key) => params.append("pinned_constraint", key));
  discovery.pinnedSettlementPoints.forEach((point) => params.append("pinned_sp", point));
  if (selection?.kind === "constraint" || selection?.kind === "cell") params.set("constraint", selection.constraintKey);
  if (selection?.kind === "settlementPoint" || selection?.kind === "cell") params.set("sp", selection.settlementPoint);
  const query = params.toString();
  return query ? `?${query}` : "";
}

export default function MatrixWorkspace({ timestamp, routeSearch, onSelectionRouteChange, onNavigateToMap }: Props) {
  const [frame, setFrame] = useState<MatrixFrame | null>(() =>
    rememberedFrame?.interval_ts === timestamp?.toISOString() ? rememberedFrame : null
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [requestVersion, setRequestVersion] = useState(0);
  const [valueMode, setValueMode] = useState<MatrixValueMode>(rememberedValueMode);
  const [muSource, setMuSource] = useState<MatrixMuSource>(rememberedMuSource);
  const [selection, setSelection] = useState<MatrixSelection>(() => selectionFromSearch(routeSearch) ?? rememberedSelection);
  const [discovery, setDiscovery] = useState<DiscoveryState>(() => discoveryFromSearch(routeSearch));
  const [inspectorCollapsed, setInspectorCollapsed] = useState(rememberedInspectorCollapsed);
  const requestId = useRef(0);

  useEffect(() => {
    if (!timestamp) return;
    const controller = new AbortController();
    const id = ++requestId.current;
    setLoading(true);
    setError(null);
    void getMatrixFrame(timestamp, {
      rowPreset: discovery.rowPreset,
      constraintType: discovery.constraintType || undefined,
      constraintSearch: discovery.constraintSearch,
      settlementPointSearch: discovery.settlementPointSearch,
      columnSet: discovery.columnSet,
      pinnedConstraints: discovery.pinnedConstraints,
      pinnedSettlementPoints: discovery.pinnedSettlementPoints,
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
  }, [discovery, requestVersion, timestamp]);

  useEffect(() => {
    try {
      window.localStorage.setItem(PIN_STORAGE_KEY, JSON.stringify({
        version: 1, constraints: discovery.pinnedConstraints, settlementPoints: discovery.pinnedSettlementPoints,
      }));
    } catch {
      // Local persistence is deliberately optional; URL state remains usable.
    }
  }, [discovery.pinnedConstraints, discovery.pinnedSettlementPoints]);

  const setMode = (mode: MatrixValueMode) => {
    rememberedValueMode = mode;
    setValueMode(mode);
  };
  const setSource = (source: MatrixMuSource) => {
    rememberedMuSource = source;
    setMuSource(source);
  };

  const damPending = frame?.dam_status === "pending";
  useEffect(() => {
    if (valueMode === "contribution" && muSource === "ercotDam" && damPending) {
      rememberedMuSource = "forecast";
      setMuSource("forecast");
    }
  }, [damPending, muSource, valueMode]);

  // Selection and discovery controls are URL-addressable. A hidden selection
  // remains explicit instead of being erased when a filter changes its frame.
  useEffect(() => {
    const nextSelection = selectionFromSearch(routeSearch);
    rememberedSelection = nextSelection;
    setSelection(nextSelection);
    setDiscovery(discoveryFromSearch(routeSearch));
  }, [routeSearch]);

  // These are artifact-wide, day-stable scales—not the current filtered
  // rectangle—so a cell keeps the same color while discovery controls change.
  const legendMax = frame?.available
    ? (valueMode === "sf" ? frame.sf_day_max_abs : frame.contribution_day_max_abs)
    : 0;

  const activeTimestamp = timestamp;
  const isUsable = frame?.available && frame.rows.length > 0 && frame.columns.length > 0;
  const isUnavailable = frame && !frame.available;
  const isEmpty = frame?.available && !isUsable;
  const damUnmatchedRows = frame?.rows.filter((row) => row.ercot_dam_mu == null).length ?? 0;
  const setCollapsed = (collapsed: boolean) => {
    rememberedInspectorCollapsed = collapsed;
    setInspectorCollapsed(collapsed);
  };
  const select = (nextSelection: MatrixSelection) => {
    rememberedSelection = nextSelection;
    setSelection(nextSelection);
    // An explicit table selection is the moment the inspector becomes useful.
    rememberedInspectorCollapsed = false;
    setInspectorCollapsed(false);
    onSelectionRouteChange(matrixSearch(discovery, nextSelection));
  };
  const updateDiscovery = (next: DiscoveryState, nextSelection = selection) => {
    setDiscovery(next);
    onSelectionRouteChange(matrixSearch(next, nextSelection));
  };
  const isPinned = (value: string, kind: "constraint" | "sp") =>
    (kind === "constraint" ? discovery.pinnedConstraints : discovery.pinnedSettlementPoints).includes(value);
  const togglePin = (value: string, kind: "constraint" | "sp") => {
    const key = kind === "constraint" ? "pinnedConstraints" : "pinnedSettlementPoints";
    const values = discovery[key];
    updateDiscovery({ ...discovery, [key]: isPinned(value, kind)
      ? values.filter((item) => item !== value)
      : boundedPins([...values, value]) });
  };
  const selectedRowVisible = !selection || selection.kind === "settlementPoint" || Boolean(frame?.rows.some((row) => row.constraint_key === selection.constraintKey));
  const selectedColumnVisible = !selection || selection.kind === "constraint" || Boolean(frame?.columns.some((column) => column.settlement_point === selection.settlementPoint));
  const selectionHidden = Boolean(selection && (!selectedRowVisible || !selectedColumnVisible));
  const revealSelection = () => {
    if (!selection) return;
    let next = discovery;
    if (selection.kind === "constraint" || selection.kind === "cell") next = { ...next, pinnedConstraints: boundedPins([...next.pinnedConstraints, selection.constraintKey]) };
    if (selection.kind === "settlementPoint" || selection.kind === "cell") next = { ...next, pinnedSettlementPoints: boundedPins([...next.pinnedSettlementPoints, selection.settlementPoint]) };
    updateDiscovery(next);
  };
  const resetView = () => {
    try { window.localStorage.removeItem(PIN_STORAGE_KEY); } catch { /* Reset still works in memory. */ }
    rememberedSelection = null;
    setSelection(null);
    updateDiscovery({ ...DEFAULT_DISCOVERY, pinnedConstraints: [], pinnedSettlementPoints: [] }, null);
  };

  return (
    <main className="matrix-workspace" aria-labelledby="matrix-title">
      <section className="matrix-workspace__toolbar">
        <div className="matrix-workspace__heading">
          <span className="label">Explorer / matrix</span>
          <div className="matrix-workspace__title-row">
            <h1 id="matrix-title">Constraint × settlement point</h1>
            <div className="matrix-workspace__controls matrix-workspace__controls--header" aria-label="Matrix value controls">
              <div className="matrix-workspace__toggle">
                <button type="button" className={valueMode === "sf" ? "is-active" : ""} onClick={() => setMode("sf")}>Shift Factor</button>
                <button type="button" className={valueMode === "contribution" ? "is-active" : ""} onClick={() => setMode("contribution")}>Contribution</button>
              </div>
              {valueMode === "contribution" && <div className="matrix-workspace__toggle">
                <button type="button" className={muSource === "forecast" ? "is-active" : ""} onClick={() => setSource("forecast")}>Forecast μ</button>
                <button type="button" disabled={damPending} title={damPending ? "ERCOT DAM μ has not been published for this hour" : undefined} className={muSource === "ercotDam" ? "is-active" : ""} onClick={() => setSource("ercotDam")}>ERCOT DAM μ</button>
              </div>}
            </div>
          </div>
          <p>{activeTimestamp ? `${formatCT(activeTimestamp, "MMM d, yyyy HH:mm")} CT` : "Waiting for playback data"}</p>
        </div>
        <div className="matrix-workspace__control-row">
          <div className="matrix-workspace__discovery" aria-label="Matrix discovery controls">
            <label>Constraints <input value={discovery.constraintSearch} onChange={(event) => updateDiscovery({ ...discovery, constraintSearch: event.target.value.slice(0, 64) })} placeholder="Search name or contingency" /></label>
            <label>Settlement points <input value={discovery.settlementPointSearch} onChange={(event) => updateDiscovery({ ...discovery, settlementPointSearch: event.target.value.slice(0, 64) })} placeholder="Search settlement point" /></label>
            <label>Rows <select value={discovery.rowPreset} onChange={(event) => updateDiscovery({ ...discovery, rowPreset: event.target.value as RowPreset })}>
              <option value="top30">Top 30 forecast contribution</option><option value="top100">Top 100</option><option value="pinned">Pinned constraints</option>
            </select></label>
            <label>Type <select value={discovery.constraintType} onChange={(event) => updateDiscovery({ ...discovery, constraintType: event.target.value as ConstraintType | "" })}>
              <option value="">All types</option><option value="gtc">GTC</option><option value="transmission">Transmission</option><option value="radial">Radial</option>
            </select></label>
            <label>Columns <select value={discovery.columnSet} onChange={(event) => updateDiscovery({ ...discovery, columnSet: event.target.value as ColumnSet })}>
              <option value="core">Core exposures</option><option value="anchors">Hubs / load zones</option><option value="pinned">Pinned settlement points</option><option value="core_pinned">Core + pinned</option>
            </select></label>
            <button type="button" onClick={resetView}>Reset view</button>
          </div>
          {isUsable && frame && <MatrixLegend mode={valueMode} maxAbs={legendMax} />}
        </div>
      </section>

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
        <section className="matrix-workspace__surface" aria-busy={loading}>
          <div className="matrix-workspace__meta">
            <span>Run {frame.run_id}</span>
            <span>Delivery day {frame.delivery_date}</span>
            <span>{frame.rows.length} of {frame.total_constraint_count} constraints</span>
            <span>{frame.columns.length} of {frame.total_settlement_point_count} settlement points</span>
            {loading && <span>Updating frame…</span>}
          </div>
          <div className={`matrix-workspace__notices${selectionHidden || (valueMode === "contribution" && frame.dam_status !== "available") ? " has-notices" : ""}`}>
            {selectionHidden && <div className="matrix-workspace__notice" role="status">The selected item is hidden by the current discovery view. <button type="button" onClick={revealSelection}>Reveal it</button></div>}
            {valueMode === "contribution" && frame.dam_status === "pending" && (
              <div className="matrix-workspace__notice" role="status">ERCOT DAM μ is pending; Contribution uses Forecast μ.</div>
            )}
            {valueMode === "contribution" && frame.dam_status === "partial" && (
              <div className="matrix-workspace__notice" role="status">DAM μ: {frame.rows.length - damUnmatchedRows}/{frame.rows.length} constraints matched; unmatched cells are unavailable.</div>
            )}
          </div>
          <MatrixGrid frame={frame} mode={valueMode} muSource={muSource} selection={selection} maxAbs={legendMax} onSelect={select} />
          <MatrixInspector frame={frame} selection={selection} collapsed={inspectorCollapsed} onCollapsedChange={setCollapsed} onNavigateToMap={onNavigateToMap} pinnedConstraints={discovery.pinnedConstraints} pinnedSettlementPoints={discovery.pinnedSettlementPoints} onToggleConstraintPin={(key) => togglePin(key, "constraint")} onToggleSettlementPointPin={(point) => togglePin(point, "sp")} />
        </section>
      )}

      {!timestamp && !loading && (
        <section className="matrix-workspace__state" role="status">
          <h2>Waiting for a playback hour</h2>
          <p>Choose an available timestamp in the shared playback scrubber to load its Matrix frame.</p>
        </section>
      )}

      <style>{`
        .matrix-workspace { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; padding: 16px; gap: 12px; background: var(--bg-base); }
        .matrix-workspace__toolbar { display: flex; align-items: stretch; flex-direction: column; gap: 10px; }
        .matrix-workspace__heading { min-width: 0; }
        .matrix-workspace__title-row { align-items: center; display: flex; flex-wrap: wrap; gap: 12px; }
        .matrix-workspace h1 { margin: 3px 0; font: 600 var(--fs-xl)/1.2 var(--font-label); color: var(--text-primary); }
        .matrix-workspace p, .matrix-workspace__meta { color: var(--text-secondary); font-size: var(--fs-label); }
        .matrix-workspace__control-row { align-items: end; display: flex; gap: 16px; justify-content: space-between; }
        .matrix-workspace__controls { align-items: end; display: flex; gap: 10px; flex-wrap: wrap; }
        .matrix-workspace__controls--header { gap: 12px; margin-left: 8px; }
        .matrix-workspace__toggle { display: flex; gap: 7px; }
        .matrix-workspace__discovery { align-items: end; display: flex; flex: 1; flex-wrap: wrap; gap: 8px; }
        .matrix-workspace__discovery label { color: var(--text-secondary); display: grid; font-size: var(--fs-micro); gap: 3px; }
        .matrix-workspace__discovery input, .matrix-workspace__discovery select { background: var(--bg-surface); border: 1px solid var(--border); color: var(--text-primary); font: var(--fs-label) var(--font-sans); min-height: 30px; padding: 4px 6px; }
        .matrix-workspace__discovery input { min-width: 175px; }
        .matrix-workspace button { border: 0; background: transparent; color: var(--text-secondary); cursor: pointer; font: 500 var(--fs-label) var(--font-sans); padding: 6px 8px; }
        .matrix-workspace__toggle button { background: var(--bg-surface); border: 1px solid var(--border); color: var(--text-secondary); }
        .matrix-workspace__controls--header button { font-weight: 600; padding: 7px 11px; }
        .matrix-workspace__toggle button.is-active { background: var(--accent-dim); border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); color: var(--accent); }
        .matrix-workspace button:disabled { cursor: not-allowed; color: var(--text-muted); }
        .matrix-workspace__loading { display: grid; flex: 1; place-items: center; color: var(--text-secondary); }
        .matrix-workspace__state { align-self: center; background: var(--bg-panel); border: 1px solid var(--border); box-shadow: var(--shadow-panel); max-width: 500px; padding: 22px; width: min(500px, 100%); }
        .matrix-workspace__state h2 { font: 600 var(--fs-lg) var(--font-label); margin: 0 0 8px; }
        .matrix-workspace__state p { line-height: 1.45; }
        .matrix-workspace__state button { background: var(--accent-dim); color: var(--accent); margin-top: 14px; }
        .matrix-workspace__surface { display: grid; min-height: 0; flex: 1; grid-template-rows: auto auto minmax(180px, 1fr) auto; border: 1px solid var(--border); background: var(--bg-panel); overflow: hidden; }
        .matrix-workspace__meta { display: flex; flex-wrap: wrap; gap: 12px; padding: 8px 10px; border-bottom: 1px solid var(--border); }
        .matrix-workspace__notices { min-height: 0; }
        .matrix-workspace__notices.has-notices { border-bottom: 1px solid var(--border); display: grid; gap: 1px; }
        .matrix-workspace__notice { background: var(--accent-dim); color: var(--text-secondary); font-size: var(--fs-label); padding: 5px 10px; }
        .matrix-grid { overflow: auto; min-height: 0; outline: none; }
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
        .matrix-inspector { background: var(--bg-surface); border-top: 1px solid var(--border); min-height: 42px; position: relative; z-index: 4; }
        .matrix-inspector h3 { color: var(--text-primary); font: 600 var(--fs-md) var(--font-label); margin: 0; }
        .matrix-workspace .matrix-inspector__collapse { align-items: center; background: transparent; border: 0; color: var(--text-secondary); cursor: pointer; display: flex; height: 38px; justify-content: center; line-height: 1; margin: 0; padding: 0; position: absolute; right: 4px; top: 2px; width: 38px; z-index: 1; }
        .matrix-workspace .matrix-inspector__collapse:hover { color: var(--accent); }
        .matrix-inspector__collapse svg { display: block; fill: none; height: 24px; stroke: currentColor; stroke-linecap: round; stroke-linejoin: round; stroke-width: 2.5; transition: transform 160ms ease; width: 24px; }
        .matrix-inspector__collapse svg.is-collapsed { transform: rotate(180deg); }
        .matrix-inspector__collapsed-title { align-items: center; color: var(--text-secondary); display: flex; font: 500 var(--fs-label) var(--font-label); min-height: 42px; padding: 0 50px 0 10px; }
        .matrix-inspector__body { color: var(--text-secondary); font-size: var(--fs-md); line-height: 1.45; max-height: 320px; overflow: auto; padding: 14px 42px 16px 12px; }
        .matrix-inspector__body > p { margin: 0; }
        .matrix-inspector__table-wrap { width: 100%; }.matrix-inspector__table-wrap h3 { margin: 0 0 8px; text-transform: uppercase; }
        .matrix-inspector__table { border-collapse: collapse; font-size: var(--fs-label); table-layout: fixed; width: 100%; }.matrix-inspector__table th, .matrix-inspector__table td { border-bottom: 1px solid var(--border); padding: 5px 6px; text-align: left; vertical-align: top; }.matrix-inspector__table thead th { color: var(--text-muted); font: 600 var(--fs-micro) var(--font-label); letter-spacing: .04em; text-transform: uppercase; }.matrix-inspector__table thead th:nth-child(1) { width: 15%; }.matrix-inspector__table thead th:nth-child(2) { width: 21%; }.matrix-inspector__table thead th:nth-child(3) { width: 20%; }.matrix-inspector__table thead th:nth-child(4) { width: 44%; }.matrix-inspector__table th[scope="row"] { color: var(--text-secondary); font-weight: 500; }.matrix-inspector__table td { color: var(--text-primary); font: 500 var(--fs-label) var(--font-mono); overflow-wrap: anywhere; }.matrix-inspector__table tr:last-child > * { border-bottom: 0; }
        .matrix-inspector__table a { color: var(--accent); font-family: var(--font-sans); }.matrix-inspector__pin { accent-color: var(--accent); cursor: pointer; height: 15px; margin: 0; width: 15px; }
        .matrix-legend { flex: 0 0 240px; width: 240px; }
        .matrix-legend__title { color: var(--text-secondary); margin-bottom: 4px; }
        .matrix-legend__bar { height: 8px; }
        .matrix-legend__ticks, .matrix-legend__signs { display: flex; justify-content: space-between; font-size: 9px; margin-top: 3px; }
        .matrix-legend__signs { color: var(--text-secondary); }
        @media (max-width: 767px) { .matrix-workspace { padding: 10px; } .matrix-workspace__control-row { align-items: start; flex-direction: column; } .matrix-inspector__metrics div { grid-template-columns: minmax(0, 1fr) auto; }.matrix-grid__corner, .matrix-grid__row { min-width: 155px; max-width: 155px; } .matrix-grid::before { color: var(--text-secondary); content: "Scroll horizontally to inspect settlement points"; display: block; font-size: var(--fs-micro); padding: 5px 8px; position: sticky; left: 0; } }
      `}</style>
    </main>
  );
}
