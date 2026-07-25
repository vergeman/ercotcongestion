import { useEffect, useMemo, useRef, useState } from "react";
import type { MatrixFrame } from "../api/types";
import { getMatrixFrame } from "../api/matrixFrames";
import MatrixGrid from "../components/matrix/MatrixGrid";
import MatrixLegend from "../components/matrix/MatrixLegend";
import MatrixInspector from "../components/matrix/MatrixInspector";
import {
  matrixCellSf,
  matrixContribution,
  type MatrixMuSource,
  type MatrixSelection,
  type MatrixValueMode,
} from "../lib/matrix";
import { formatCT } from "../lib/time";

let rememberedValueMode: MatrixValueMode = "sf";
let rememberedMuSource: MatrixMuSource = "forecast";
let rememberedInspectorCollapsed = false;
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

  const summary = useMemo(() => {
    if (!frame?.available || valueMode !== "contribution") return null;
    const sum = frame.rows.reduce((total, row, rowIndex) => {
      const mu = muSource === "forecast" ? row.forecast_mu : row.ercot_dam_mu;
      return total + frame.columns.reduce((rowTotal, _, columnIndex) =>
        rowTotal + (matrixContribution(
          matrixCellSf(frame.sf.values, rowIndex, columnIndex, frame.columns.length),
          mu
        ) ?? 0), 0);
    }, 0);
    return sum;
  }, [frame, muSource, valueMode]);

  const legendMax = useMemo(() => {
    if (!frame?.available) return 0;
    const values = frame.rows.flatMap((row, rowIndex) => frame.columns.map((_, columnIndex) => {
      const sf = matrixCellSf(frame.sf.values, rowIndex, columnIndex, frame.columns.length);
      return valueMode === "sf" ? sf : matrixContribution(sf, muSource === "forecast" ? row.forecast_mu : row.ercot_dam_mu);
    }));
    return Math.max(0, ...values.flatMap((value) => value == null ? [] : [Math.abs(value)]));
  }, [frame, muSource, valueMode]);

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
    onSelectionRouteChange(matrixSearch(discovery, nextSelection));
  };
  const updateDiscovery = (next: DiscoveryState, nextSelection = selection) => {
    setDiscovery(next);
    onSelectionRouteChange(matrixSearch(next, nextSelection));
  };
  const isPinned = (value: string, kind: "constraint" | "sp") =>
    (kind === "constraint" ? discovery.pinnedConstraints : discovery.pinnedSettlementPoints).includes(value);
  const toggleSelectedPins = () => {
    if (!selection) return;
    let next = discovery;
    if (selection.kind === "constraint" || selection.kind === "cell") {
      next = { ...next, pinnedConstraints: isPinned(selection.constraintKey, "constraint")
        ? next.pinnedConstraints.filter((key) => key !== selection.constraintKey)
        : boundedPins([...next.pinnedConstraints, selection.constraintKey]) };
    }
    if (selection.kind === "settlementPoint" || selection.kind === "cell") {
      next = { ...next, pinnedSettlementPoints: isPinned(selection.settlementPoint, "sp")
        ? next.pinnedSettlementPoints.filter((point) => point !== selection.settlementPoint)
        : boundedPins([...next.pinnedSettlementPoints, selection.settlementPoint]) };
    }
    updateDiscovery(next);
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
        <div>
          <span className="label">Explorer / matrix</span>
          <h1 id="matrix-title">Constraint × settlement point</h1>
          <p>{activeTimestamp ? `${formatCT(activeTimestamp, "MMM d, yyyy HH:mm")} CT` : "Waiting for playback data"}</p>
        </div>
        <div className="matrix-workspace__controls" aria-label="Matrix value controls">
          <fieldset>
            <legend>Value</legend>
            <button type="button" className={valueMode === "sf" ? "is-active" : ""} onClick={() => setMode("sf")}>Shift Factor</button>
            <button type="button" className={valueMode === "contribution" ? "is-active" : ""} onClick={() => setMode("contribution")}>Contribution</button>
          </fieldset>
          {valueMode === "contribution" && (
            <fieldset>
              <legend>μ source</legend>
              <button type="button" className={muSource === "forecast" ? "is-active" : ""} onClick={() => setSource("forecast")}>Forecast</button>
              <button type="button" disabled={damPending} title={damPending ? "ERCOT DAM μ has not been published for this hour" : undefined} className={muSource === "ercotDam" ? "is-active" : ""} onClick={() => setSource("ercotDam")}>ERCOT DAM</button>
            </fieldset>
          )}
        </div>
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
          {selection && <button type="button" onClick={toggleSelectedPins}>Pin selected</button>}
          <button type="button" onClick={resetView}>Reset view</button>
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
            <span>{frame.fit_window_start && frame.fit_window_end ? `Fit ${frame.fit_window_start}–${frame.fit_window_end}` : "Fit provenance unavailable"}</span>
            <span>Recovered implied shift factors</span>
            <span>{frame.dam_status === "pending" ? "DAM μ pending — forecast-only" : frame.dam_status === "partial" ? "DAM μ partial match" : "DAM μ available"}</span>
            <span>{frame.rows.length} of {frame.total_constraint_count} constraints</span>
            <span>{frame.columns.length} of {frame.total_settlement_point_count} settlement points</span>
            {loading && <span>Updating frame…</span>}
          </div>
          {selectionHidden && <div className="matrix-workspace__notice" role="status">The selected item is hidden by the current discovery view. <button type="button" onClick={revealSelection}>Reveal it</button></div>}
          {valueMode === "contribution" && frame.dam_status === "pending" && (
            <div className="matrix-workspace__notice" role="status">ERCOT DAM μ has not been published for this hour; Contribution uses Forecast μ.</div>
          )}
          {valueMode === "contribution" && frame.dam_status === "partial" && (
            <div className="matrix-workspace__notice" role="status">ERCOT DAM μ matched {frame.rows.length - damUnmatchedRows} of {frame.rows.length} constraints. Unmatched contribution cells are unavailable.</div>
          )}
          <MatrixGrid frame={frame} mode={valueMode} muSource={muSource} selection={selection} onSelect={select} />
          <MatrixInspector frame={frame} selection={selection} collapsed={inspectorCollapsed} onCollapsedChange={setCollapsed} onNavigateToMap={onNavigateToMap} />
          <footer className="matrix-workspace__footer">
            <MatrixLegend mode={valueMode} maxAbs={legendMax} />
            <div className="matrix-workspace__summary">
              {valueMode === "contribution" ? <><span className="label">Visible-row contribution</span><strong>${(summary ?? 0).toFixed(2)}/MWh</strong></> : <span>SF is dimensionless. Positive/export is blue; negative/import is red.</span>}
            </div>
          </footer>
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
        .matrix-workspace__toolbar { display: flex; align-items: end; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
        .matrix-workspace h1 { margin: 3px 0; font: 600 var(--fs-xl)/1.2 var(--font-label); color: var(--text-primary); }
        .matrix-workspace p, .matrix-workspace__meta, .matrix-workspace__summary { color: var(--text-secondary); font-size: var(--fs-label); }
        .matrix-workspace__controls { display: flex; gap: 10px; flex-wrap: wrap; }
        .matrix-workspace__discovery { align-items: end; display: flex; flex-wrap: wrap; gap: 8px; width: 100%; }
        .matrix-workspace__discovery label { color: var(--text-secondary); display: grid; font-size: var(--fs-micro); gap: 3px; }
        .matrix-workspace__discovery input, .matrix-workspace__discovery select { background: var(--bg-surface); border: 1px solid var(--border); color: var(--text-primary); font: var(--fs-label) var(--font-sans); min-height: 30px; padding: 4px 6px; }
        .matrix-workspace__discovery input { min-width: 175px; }
        .matrix-workspace fieldset { display: flex; border: 0; gap: 1px; background: var(--bg-surface); padding: 2px; }
        .matrix-workspace legend { color: var(--text-secondary); font-size: var(--fs-micro); margin-bottom: 3px; }
        .matrix-workspace button { border: 0; background: transparent; color: var(--text-secondary); cursor: pointer; font: 500 var(--fs-label) var(--font-sans); padding: 6px 8px; }
        .matrix-workspace button.is-active { background: var(--accent-dim); color: var(--accent); }
        .matrix-workspace button:disabled { cursor: not-allowed; color: var(--text-muted); }
        .matrix-workspace__loading { display: grid; flex: 1; place-items: center; color: var(--text-secondary); }
        .matrix-workspace__state { align-self: center; background: var(--bg-panel); border: 1px solid var(--border); box-shadow: var(--shadow-panel); max-width: 500px; padding: 22px; width: min(500px, 100%); }
        .matrix-workspace__state h2 { font: 600 var(--fs-lg) var(--font-label); margin: 0 0 8px; }
        .matrix-workspace__state p { line-height: 1.45; }
        .matrix-workspace__state button { background: var(--accent-dim); color: var(--accent); margin-top: 14px; }
        .matrix-workspace__surface { display: grid; min-height: 0; flex: 1; grid-template-rows: auto minmax(180px, 1fr) auto auto; border: 1px solid var(--border); background: var(--bg-panel); overflow: hidden; }
        .matrix-workspace__meta { display: flex; flex-wrap: wrap; gap: 12px; padding: 8px 10px; border-bottom: 1px solid var(--border); }
        .matrix-workspace__notice { background: var(--accent-dim); border-bottom: 1px solid var(--border); color: var(--text-secondary); font-size: var(--fs-label); padding: 6px 10px; }
        .matrix-workspace__footer { display: flex; align-items: end; justify-content: space-between; gap: 18px; padding: 9px 10px; border-top: 1px solid var(--border); }
        .matrix-workspace__summary { text-align: right; max-width: 310px; }
        .matrix-workspace__summary strong { display: block; color: var(--text-primary); font: 600 var(--fs-md) var(--font-mono); margin-top: 3px; }
        .matrix-grid { overflow: auto; min-height: 0; outline: none; }
        .matrix-grid:focus-visible, .matrix-grid [tabindex="0"]:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; position: relative; z-index: 3; }
        .matrix-grid table { border-collapse: separate; border-spacing: 0; font-size: var(--fs-micro); width: max-content; min-width: 100%; }
        .matrix-grid th, .matrix-grid td { border-right: 1px solid color-mix(in srgb, var(--border) 70%, transparent); border-bottom: 1px solid color-mix(in srgb, var(--border) 70%, transparent); }
        .matrix-grid thead th { background: var(--bg-panel); position: sticky; top: 0; z-index: 2; height: 50px; vertical-align: bottom; }
        .matrix-grid__corner { left: 0; z-index: 4 !important; min-width: 205px; padding: 7px 10px; text-align: left; }
        .matrix-grid__corner span, .matrix-grid__row span { display: block; color: var(--text-primary); font-weight: 600; }
        .matrix-grid small { color: var(--text-secondary); display: block; font-size: 9px; font-weight: 400; margin-top: 2px; }
        .matrix-grid__column { min-width: 72px; max-width: 72px; cursor: pointer; padding: 6px; text-align: right; white-space: nowrap; }
        .matrix-grid__column > span { color: var(--text-primary); display: block; overflow: hidden; text-overflow: ellipsis; }
        .matrix-grid__row { background: var(--bg-panel); cursor: pointer; left: 0; min-width: 205px; max-width: 205px; padding: 6px 10px; position: sticky; text-align: left; z-index: 1; }
        .matrix-grid__row > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .matrix-grid__cell { color: var(--text-primary); cursor: pointer; font: 500 var(--fs-micro) var(--font-mono); min-width: 72px; padding: 7px 6px; text-align: right; white-space: nowrap; }
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
        .matrix-inspector__body { color: var(--text-secondary); font-size: var(--fs-label); max-height: 280px; overflow: auto; padding: 12px 42px 12px 10px; }
        .matrix-inspector__body > p { margin: 0; }
        .matrix-inspector__key { font: 500 var(--fs-micro) var(--font-mono); margin: 3px 0 10px; }.matrix-inspector__key span { color: var(--text-muted); display: block; font: var(--fs-micro) var(--font-sans); margin-bottom: 2px; }
        .matrix-inspector__metrics { display: grid; gap: 8px 18px; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); margin: 0; }
        .matrix-inspector__metrics div { min-width: 0; }.matrix-inspector__metrics dt { color: var(--text-muted); font-size: var(--fs-micro); }.matrix-inspector__metrics dd { color: var(--text-primary); font: 500 var(--fs-label) var(--font-mono); margin: 2px 0 0; overflow-wrap: anywhere; }
        .matrix-inspector__actions { display: flex; flex-wrap: wrap; gap: 12px; margin: 12px 0 0; }.matrix-inspector__actions a { color: var(--accent); font-size: var(--fs-label); }.matrix-inspector__warning { background: color-mix(in srgb, var(--warning, #f59e0b) 16%, transparent); border-left: 3px solid var(--warning, #f59e0b); color: var(--text-primary); margin: 12px 0 0; padding: 7px 9px; }
        .matrix-legend { width: 240px; }
        .matrix-legend__title { color: var(--text-secondary); margin-bottom: 4px; }
        .matrix-legend__bar { height: 8px; }
        .matrix-legend__ticks, .matrix-legend__signs { display: flex; justify-content: space-between; font-size: 9px; margin-top: 3px; }
        .matrix-legend__signs { color: var(--text-secondary); }
        @media (max-width: 767px) { .matrix-workspace { padding: 10px; } .matrix-workspace__toolbar { align-items: start; } .matrix-workspace__footer { align-items: start; flex-direction: column; } .matrix-workspace__summary { max-width: none; text-align: left; } .matrix-grid__corner, .matrix-grid__row { min-width: 155px; max-width: 155px; } .matrix-grid::before { color: var(--text-secondary); content: "Scroll horizontally to inspect settlement points"; display: block; font-size: var(--fs-micro); padding: 5px 8px; position: sticky; left: 0; } }
      `}</style>
    </main>
  );
}
