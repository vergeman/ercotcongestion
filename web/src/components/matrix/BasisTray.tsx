import { constraintName, usd } from "../brief/briefFormat";
import { shiftFactorColor } from "../../lib/colors";
import type { BasisResult, BasisRow } from "../../lib/basis";

// 0139/0006 — the basis tray docked at the bottom of the SF lens (Nodes tab).
// Not a third lens, not a modal: A is the current selection, B is an opt-in
// second node, and once both are set the tray expands into the congestion-basis
// decomposition. This component is purely presentational — the workspace owns
// the A/B ids, the picking flag, and the fetched/joined `BasisResult`.

const VISIBLE_ROWS = 8;

interface Props {
  // A is always present (it derives from the SF-lens selection).
  aNode: string;
  // B is null until the user opts in (ghost-arm or shift/⌘-click a node row).
  bNode: string | null;
  // The ghost is armed: the next plain node click routes to B, not selection.
  picking: boolean;
  loading: boolean;
  // The forecast/DAM basis at the currently selected μ-source (val toggle).
  primary: BasisResult | null;
  // Echo of the SF-lens value sub-toggle driving μ ("Forecast μ" | "ERCOT DAM μ").
  muLabel: string;
  // The realized (ERCOT DAM) basis total, shown alongside the forecast basis
  // when a realized column exists and the primary is the forecast basis.
  realizedTotal?: number | null;
  // A settled congestion basis for the pair, when computable — drives the
  // "explains X% of settled basis" reconciliation line.
  settledBasis?: number | null;
  onArm: () => void;
  onSwap: () => void;
  onClear: () => void;
}

function sfCell(value: number | null) {
  if (value == null) return <td className="bt-drv__sf bt-drv__sf--absent">·</td>;
  return <td className="bt-drv__sf mono" style={{ color: shiftFactorColor(value) }}>{value.toFixed(3)}</td>;
}

function DecompRow({ row }: { row: BasisRow }) {
  return (
    <tr>
      <td className="bt-drv__key mono">{constraintName(row.constraint)}</td>
      {sfCell(row.sfA)}
      {sfCell(row.sfB)}
      <td className="mono">{row.mu == null ? "—" : usd(row.mu, 0)}</td>
      <td className={`mono${row.contrib >= 0 ? " bt-pos" : " bt-neg"}`}>{usd(row.contrib, 2)}</td>
      <td className="bt-drv__tag">{row.mutual ? "mutual" : "one-sided"}</td>
    </tr>
  );
}

function Expanded({ primary, muLabel, realizedTotal, settledBasis }: {
  primary: BasisResult;
  muLabel: string;
  realizedTotal?: number | null;
  settledBasis?: number | null;
}) {
  const { rows, total, topShare, topConstraint } = primary;
  const visible = rows.slice(0, VISIBLE_ROWS);
  const rest = rows.slice(VISIBLE_ROWS);
  const settledPct = settledBasis != null && settledBasis !== 0
    ? Math.round((total / settledBasis) * 100)
    : null;

  return (
    <div className="bt-expanded">
      <div className="bt-head">
        <div className="bt-head__totals">
          <span className="bt-eyebrow">A→B congestion basis</span>
          <span className={`bt-total mono${total >= 0 ? " bt-pos" : " bt-neg"}`}>{usd(total, 2)}<span className="bt-total__unit">/MWh</span></span>
          {realizedTotal != null && (
            <span className="bt-total-realized mono">realized {usd(realizedTotal, 2)}/MWh</span>
          )}
        </div>
        <div className="bt-head__meta">
          <span className="bt-readout">
            {topConstraint
              ? <>{Math.round(topShare * 100)}% of the basis is <b>{constraintName(topConstraint)}</b> · decomposed across {rows.length} constraint{rows.length === 1 ? "" : "s"}</>
              : "no shared constraints"}
          </span>
          <span className="bt-musrc">μ: {muLabel}</span>
        </div>
      </div>

      <table className="bt-drv">
        <thead>
          <tr><th>constraint</th><th>SF A</th><th>SF B</th><th>μ</th><th>basis $</th><th>side</th></tr>
        </thead>
        <tbody>{visible.map((row) => <DecompRow key={row.constraint} row={row} />)}</tbody>
      </table>
      {rest.length > 0 && (
        <details className="bt-more">
          <summary>{rest.length} more constraint{rest.length === 1 ? "" : "s"}</summary>
          <table className="bt-drv">
            <tbody>{rest.map((row) => <DecompRow key={row.constraint} row={row} />)}</tbody>
          </table>
        </details>
      )}

      <p className="bt-honesty">
        Congestion basis (implied SF) — no energy or loss component; not an ERCOT PTDF.
        {settledPct != null && <> Explains <b>{settledPct}%</b> of settled basis.</>}
      </p>
    </div>
  );
}

export default function BasisTray({
  aNode, bNode, picking, loading, primary, muLabel, realizedTotal, settledBasis, onArm, onSwap, onClear,
}: Props) {
  return (
    <div className={`basis-tray${bNode ? " is-open" : ""}`} aria-label="Node comparison basis">
      <div className="basis-tray__slots">
        <span className="basis-tray__label">Basis</span>
        <span className="basis-tray__slot mono"><em>A</em>{aNode}</span>
        <span className="basis-tray__op">−</span>
        {bNode ? (
          <span className="basis-tray__slot basis-tray__slot--b mono">
            <em>B</em>{bNode}
            <button type="button" className="basis-tray__ctl" title="Swap A and B" aria-label="Swap A and B" onClick={onSwap}>⇄</button>
            <button type="button" className="basis-tray__ctl" title="Clear B" aria-label="Clear B" onClick={onClear}>✕</button>
          </span>
        ) : (
          <button
            type="button"
            className={`basis-tray__ghost${picking ? " is-armed" : ""}`}
            aria-pressed={picking}
            onClick={onArm}
          >
            {picking ? "Pick B — click a node row…" : "+ pick a second node to compare"}
          </button>
        )}
        {bNode && picking && <span className="basis-tray__hint">Pick B — click a node row…</span>}
      </div>

      {bNode && (
        loading && !primary ? <div className="basis-tray__msg">Computing basis…</div>
          : primary && primary.rows.length > 0
            ? <Expanded primary={primary} muLabel={muLabel} realizedTotal={realizedTotal} settledBasis={settledBasis} />
            : <div className="basis-tray__msg">No constraints located on {aNode} or {bNode} at this hour.</div>
      )}

      <style>{`
        .basis-tray { border-top: 1px solid var(--border); background: var(--bg-panel); padding: 8px 12px 10px; flex: 0 0 auto; max-height: 42%; overflow-y: auto; overscroll-behavior: contain; }
        .basis-tray.is-open { background: color-mix(in srgb, var(--accent-dim) 22%, var(--bg-panel)); }
        .basis-tray__slots { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
        .basis-tray__label { color: var(--text-secondary); font: 600 var(--fs-xs) var(--font-label); letter-spacing: var(--track-label); text-transform: uppercase; }
        .basis-tray__slot { display: inline-flex; align-items: center; gap: 6px; background: var(--bg-surface); border: 1px solid var(--border); padding: 4px 8px; font-size: var(--fs-label); color: var(--text-primary); }
        .basis-tray__slot em { font-style: normal; color: var(--text-muted); font-size: var(--fs-micro); font-weight: 700; }
        .basis-tray__slot--b { border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); }
        .basis-tray__op { color: var(--text-muted); font-weight: 600; }
        .basis-tray__ctl { border: 0; background: transparent; color: var(--text-secondary); cursor: pointer; font-size: var(--fs-label); padding: 0 2px; line-height: 1; }
        .basis-tray__ctl:hover { color: var(--accent); }
        .basis-tray__ghost { border: 1px dashed color-mix(in srgb, var(--accent) 55%, var(--border)); background: transparent; color: var(--accent); cursor: pointer; font: 500 var(--fs-label) var(--font-sans); padding: 5px 10px; }
        .basis-tray__ghost.is-armed { background: var(--accent-dim); border-style: solid; }
        .basis-tray__hint { color: var(--accent); font-size: var(--fs-micro); }
        .basis-tray__msg { color: var(--text-secondary); font-size: var(--fs-label); padding: 10px 2px 2px; }
        .bt-expanded { margin-top: 8px; }
        .bt-head { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 8px 16px; margin-bottom: 8px; }
        .bt-head__totals { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; }
        .bt-eyebrow { color: var(--text-secondary); font: 600 var(--fs-xs) var(--font-label); letter-spacing: var(--track-label); text-transform: uppercase; }
        .bt-total { font-size: var(--fs-xl); font-weight: 600; }
        .bt-total__unit { font-size: var(--fs-label); color: var(--text-muted); font-weight: 400; margin-left: 1px; }
        .bt-total-realized { color: var(--text-secondary); font-size: var(--fs-label); }
        .bt-head__meta { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; }
        .bt-readout { color: var(--text-secondary); font-size: var(--fs-label); }
        .bt-readout b { color: var(--text-primary); }
        .bt-musrc { color: var(--text-muted); font-size: var(--fs-micro); white-space: nowrap; }
        .bt-pos { color: var(--danger, #d94444); }
        .bt-neg { color: var(--accent); }
        .bt-drv { width: 100%; border-collapse: collapse; font-size: var(--fs-label); }
        .bt-drv th, .bt-drv td { text-align: right; padding: 4px 8px; border-bottom: 1px solid color-mix(in srgb, var(--border) 55%, transparent); white-space: nowrap; }
        .bt-drv th { color: var(--text-muted); font-size: var(--fs-micro); text-transform: uppercase; letter-spacing: .04em; font-weight: 600; }
        .bt-drv th:first-child, .bt-drv td:first-child { text-align: left; }
        .bt-drv__key { max-width: 240px; overflow: hidden; text-overflow: ellipsis; }
        .bt-drv__sf--absent { color: var(--text-muted); }
        .bt-drv__tag { color: var(--text-muted); font-size: var(--fs-micro); text-transform: uppercase; letter-spacing: .03em; }
        .bt-more { margin-top: 2px; }
        .bt-more summary { color: var(--accent); cursor: pointer; font-size: var(--fs-micro); padding: 5px 2px; }
        .bt-honesty { color: var(--text-muted); font-size: var(--fs-micro); line-height: 1.5; margin: 10px 0 0; }
        .bt-honesty b { color: var(--text-secondary); }
        .mono { font-family: var(--font-mono); }
      `}</style>
    </div>
  );
}
