import { useEffect, useMemo, useRef, useState } from "react";
import type { MatrixFrame } from "../api/types";
import { getMatrixFrame } from "../api/matrixFrames";
import MatrixGrid from "../components/matrix/MatrixGrid";
import MatrixLegend from "../components/matrix/MatrixLegend";
import {
  matrixCellSf,
  matrixContribution,
  type MatrixMuSource,
  type MatrixValueMode,
} from "../lib/matrix";
import { formatCT } from "../lib/time";

let rememberedValueMode: MatrixValueMode = "sf";
let rememberedMuSource: MatrixMuSource = "forecast";

interface Props {
  timestamp: Date | null;
}

export default function MatrixWorkspace({ timestamp }: Props) {
  const [frame, setFrame] = useState<MatrixFrame | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [requestVersion, setRequestVersion] = useState(0);
  const [valueMode, setValueMode] = useState<MatrixValueMode>(rememberedValueMode);
  const [muSource, setMuSource] = useState<MatrixMuSource>(rememberedMuSource);
  const requestId = useRef(0);

  useEffect(() => {
    if (!timestamp) return;
    const controller = new AbortController();
    const id = ++requestId.current;
    setLoading(true);
    setError(null);
    void getMatrixFrame(timestamp, {}, controller.signal)
      .then((nextFrame) => {
        if (id === requestId.current) setFrame(nextFrame);
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
  }, [requestVersion, timestamp]);

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
            {loading && <span>Updating frame…</span>}
          </div>
          {valueMode === "contribution" && frame.dam_status === "pending" && (
            <div className="matrix-workspace__notice" role="status">ERCOT DAM μ has not been published for this hour; Contribution uses Forecast μ.</div>
          )}
          {valueMode === "contribution" && frame.dam_status === "partial" && (
            <div className="matrix-workspace__notice" role="status">ERCOT DAM μ matched {frame.rows.length - damUnmatchedRows} of {frame.rows.length} constraints. Unmatched contribution cells are unavailable.</div>
          )}
          <MatrixGrid frame={frame} mode={valueMode} muSource={muSource} />
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
        .matrix-workspace__surface { display: grid; min-height: 0; flex: 1; grid-template-rows: auto minmax(0, 1fr) auto; border: 1px solid var(--border); background: var(--bg-panel); overflow: hidden; }
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
        .matrix-grid__column { min-width: 72px; max-width: 72px; padding: 6px; text-align: right; white-space: nowrap; }
        .matrix-grid__column > span { color: var(--text-primary); display: block; overflow: hidden; text-overflow: ellipsis; }
        .matrix-grid__row { background: var(--bg-panel); left: 0; min-width: 205px; max-width: 205px; padding: 6px 10px; position: sticky; text-align: left; z-index: 1; }
        .matrix-grid__row > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .matrix-grid__cell { color: var(--text-primary); font: 500 var(--fs-micro) var(--font-mono); min-width: 72px; padding: 7px 6px; text-align: right; white-space: nowrap; }
        .matrix-grid__cell--unavailable { color: var(--text-muted); background: repeating-linear-gradient(-45deg, var(--bg-surface), var(--bg-surface) 3px, var(--bg-panel) 3px, var(--bg-panel) 6px) !important; }
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
