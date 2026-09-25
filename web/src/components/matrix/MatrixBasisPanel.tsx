import { constraintName, usd } from "../../lib/format";
import type { BasisResult, BasisRow } from "../../lib/basis";

// Vivid negative/positive hues for the shift-factor columns. The app's soft SF
// palette (lib/colors.ts) read as washed-out here, so this table uses fully
// saturated versions of the same magenta/teal identity.
const SF_NEGATIVE_STRONG = "#e0308f";
const SF_POSITIVE_STRONG = "#0fa588";

// 0139/0006 — the Basis lens: a full-screen, two-node congestion basis, driven
// by the sidebar node search. Slot A and slot B are each filled by a single
// click in the index (the active slot advances A→B→A); the panel decomposes
// `LMP_A,cong − LMP_B,cong` constraint-by-constraint. Purely presentational —
// the workspace owns the slot ids, the active slot, and the joined result.

type BasisSlot = "a" | "b";

interface Props {
  aNode: string | null;
  bNode: string | null;
  activeSlot: BasisSlot;
  loading: boolean;
  // The forecast/DAM basis at the selected μ-source (value sub-toggle).
  primary: BasisResult | null;
  // The realized (settled DAM) basis total for the same pair, shown alongside a
  // forecast basis when settled DAM exists.
  realizedTotal?: number | null;
  // The settled congestion basis denominator for "explains X% of settled basis".
  settledBasis?: number | null;
  onTargetSlot: (slot: BasisSlot) => void;
  onSwap: () => void;
  onClear: (slot: BasisSlot) => void;
}

function sfCell(value: number | null) {
  if (value == null) return <td className="mbp-drv__sf mbp-drv__sf--absent">·</td>;
  return <td className="mbp-drv__sf mono" style={{ color: value < 0 ? SF_NEGATIVE_STRONG : SF_POSITIVE_STRONG }}>{value.toFixed(3)}</td>;
}

function DecompRow({ row }: { row: BasisRow }) {
  return (
    <tr>
      <td className="mbp-drv__key mono">{constraintName(row.constraint)}</td>
      {sfCell(row.sfA)}
      {sfCell(row.sfB)}
      <td className="mono">{row.mu == null ? "—" : usd(row.mu, 2)}</td>
      <td className={`mono${row.contrib >= 0 ? " mbp-pos" : " mbp-neg"}`}>{usd(row.contrib, 2)}</td>
    </tr>
  );
}

function Slot({ label, node, active, onTarget, onClear }: {
  label: string; node: string | null; active: boolean; onTarget: () => void; onClear: () => void;
}) {
  return (
    <span className={`mbp-slot${active ? " is-active" : ""}${node ? " is-filled" : ""}`}>
      <button type="button" className="mbp-slot__pick" onClick={onTarget} aria-pressed={active}
        title={`Target slot ${label} — the next node you click fills it`}>
        <em>{label}</em>
        <span className="mono">{node ?? "pick a node →"}</span>
      </button>
      {node && (
        <button type="button" className="mbp-slot__clear" onClick={onClear} aria-label={`Clear slot ${label}`} title={`Clear slot ${label}`}>✕</button>
      )}
    </span>
  );
}

function Decomposition({ primary, realizedTotal, settledBasis }: {
  primary: BasisResult; realizedTotal?: number | null; settledBasis?: number | null;
}) {
  const { rows, total, topShare, topConstraint } = primary;
  const settledPct = settledBasis != null && settledBasis !== 0
    ? Math.round((total / settledBasis) * 100)
    : null;

  return (
    <div className="mbp-decomp">
      <div className="mbp-stats">
        <span className="mbp-eyebrow">Congestion basis</span>
        <div className="mbp-stats__totals">
          <span className={`mbp-total mono${total >= 0 ? " mbp-pos" : " mbp-neg"}`}>{usd(total, 2)}<span className="mbp-total__unit">/MWh</span></span>
          {realizedTotal != null && (
            <span className="mbp-total-realized mono">settled {usd(realizedTotal, 2)}/MWh</span>
          )}
        </div>
        <p className="mbp-readout">
          {topConstraint
            ? <>{Math.round(topShare * 100)}% of the basis is <b>{constraintName(topConstraint)}</b> · decomposed across {rows.length} constraint{rows.length === 1 ? "" : "s"}</>
            : "no shared constraints"}
        </p>
      </div>

      <div className="mbp-table-wrap">
        <table className="mbp-drv">
          <thead>
            <tr><th>Constraint</th><th>Shift Factor A</th><th>Shift Factor B</th><th title="Constraint shadow price μ at the scrubbed hour — forecast or ERCOT DAM per the Data toggle. Not a total or time-average.">Shadow Price (μ)</th><th>Basis ($)</th></tr>
          </thead>
          <tbody>{rows.map((row) => <DecompRow key={row.constraint} row={row} />)}</tbody>
        </table>
      </div>

      <p className="mbp-honesty">
        Congestion basis (implied SF) — no energy or loss component; not an ERCOT PTDF.
        {settledPct != null && <> Explains <b>{settledPct}%</b> of settled basis.</>}
      </p>
    </div>
  );
}

export default function MatrixBasisPanel({
  aNode, bNode, activeSlot, loading, primary, realizedTotal, settledBasis, onTargetSlot, onSwap, onClear,
}: Props) {
  const bothSet = Boolean(aNode && bNode);
  return (
    <div className="mbp" aria-label="Node comparison basis">
      <header className="mbp-head">
        <div className="mbp-slots">
          <Slot label="A" node={aNode} active={activeSlot === "a"} onTarget={() => onTargetSlot("a")} onClear={() => onClear("a")} />
          <span className="mbp-op">−</span>
          <Slot label="B" node={bNode} active={activeSlot === "b"} onTarget={() => onTargetSlot("b")} onClear={() => onClear("b")} />
          <button type="button" className="mbp-swap" onClick={onSwap} disabled={!bothSet} title="Swap A and B" aria-label="Swap A and B">⇄</button>
        </div>
        <p className="mbp-hint">
          {bothSet
            ? <>Click a settlement point in the list to replace slot <b>{activeSlot.toUpperCase()}</b>.</>
            : <>Click a settlement point in the list to fill slot <b>{activeSlot.toUpperCase()}</b>.</>}
        </p>
      </header>

      <div className="mbp-body">
        {!bothSet ? (
          <div className="mbp-empty">
            <h3>Compare two settlement points</h3>
            <p>Pick a node for <b>A</b> and another for <b>B</b> from the index. Their implied shift-factor columns join into a congestion basis — <code>LMP_A,cong − LMP_B,cong</code> — decomposed constraint by constraint.</p>
          </div>
        ) : loading && !primary ? (
          <div className="mbp-msg">Computing basis…</div>
        ) : primary && primary.rows.length > 0 ? (
          <Decomposition primary={primary} realizedTotal={realizedTotal} settledBasis={settledBasis} />
        ) : (
          <div className="mbp-msg">No constraints located on {aNode} or {bNode} at this hour.</div>
        )}
      </div>

      <style>{`
        .mbp { height: 100%; min-height: 0; display: flex; flex-direction: column; }
        .mbp-head { flex: 0 0 auto; border-bottom: 1px solid var(--border); padding: 12px 18px; }
        .mbp-slots { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
        .mbp-slot { display: inline-flex; align-items: stretch; border: 1px solid var(--border); background: var(--bg-surface); }
        .mbp-slot.is-filled { border-color: color-mix(in srgb, var(--accent) 40%, var(--border)); }
        .mbp-slot.is-active { box-shadow: 0 0 0 2px var(--accent); border-color: var(--accent); }
        .mbp-slot__pick { display: inline-flex; align-items: center; gap: 8px; border: 0; background: transparent; cursor: pointer; padding: 7px 11px; color: var(--text-primary); font-size: var(--fs-md); }
        .mbp-slot__pick em { font-style: normal; color: var(--text-muted); font-weight: 700; font-size: var(--fs-label); }
        .mbp-slot.is-filled .mbp-slot__pick em { color: var(--accent); }
        .mbp-slot__pick span:not(.is-empty) { color: var(--text-primary); }
        .mbp-slot:not(.is-filled) .mbp-slot__pick span { color: var(--text-muted); font-family: var(--font-sans); font-size: var(--fs-label); }
        .mbp-slot__clear { border: 0; background: transparent; color: var(--text-secondary); cursor: pointer; padding: 0 8px; }
        .mbp-slot__clear:hover { color: var(--accent); }
        .mbp-op { color: var(--text-muted); font-weight: 600; font-size: var(--fs-lg); }
        .mbp-swap { border: 1px solid var(--border); background: var(--bg-surface); color: var(--text-secondary); cursor: pointer; font-size: var(--fs-md); padding: 6px 10px; }
        .mbp-swap:disabled { cursor: not-allowed; color: var(--text-muted); opacity: .5; }
        .mbp-swap:not(:disabled):hover { color: var(--accent); border-color: color-mix(in srgb, var(--accent) 45%, var(--border)); }
        /* Scope with the panel root so this out-specifies the workspace's
           .matrix-workspace p { margin: 0 } reset (both are 0,1,1). */
        .mbp .mbp-hint { color: var(--text-secondary); font-size: var(--fs-label); margin: 10px 0 0; }
        .mbp-hint b { color: var(--accent); }
        .mbp-body { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 0 18px; }
        .mbp-empty { max-width: 560px; margin: 48px auto; text-align: center; color: var(--text-secondary); }
        .mbp-empty h3 { font: 600 var(--fs-lg) var(--font-label); color: var(--text-primary); margin: 0 0 10px; }
        .mbp-empty p { line-height: 1.55; }
        .mbp-empty code { font-family: var(--font-mono); background: var(--bg-surface); padding: 1px 5px; border: 1px solid var(--border); }
        .mbp-msg { color: var(--text-secondary); font-size: var(--fs-md); padding: 32px 2px; }
        .mbp-decomp { padding: 16px 0 24px; }
        .mbp-stats { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; margin-bottom: 16px; }
        .mbp-stats__totals { display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap; }
        .mbp-eyebrow { color: var(--text-secondary); font: 600 var(--fs-xs) var(--font-label); letter-spacing: var(--track-label); text-transform: uppercase; }
        .mbp-total { font-size: var(--fs-2xl, 28px); font-weight: 600; }
        .mbp-total__unit { font-size: var(--fs-md); color: var(--text-muted); font-weight: 400; margin-left: 2px; }
        .mbp-total-realized { color: var(--text-secondary); font-size: var(--fs-md); }
        .mbp .mbp-readout { color: var(--text-secondary); font-size: var(--fs-md); margin: 2px 0 0; }
        .mbp-readout b { color: var(--text-primary); }
        .mbp-pos { color: var(--danger, #d94444); }
        .mbp-neg { color: var(--accent); }
        .mbp-table-wrap { overflow-x: auto; }
        .mbp-drv { width: 100%; border-collapse: collapse; font-size: var(--fs-label); }
        .mbp-drv th, .mbp-drv td { text-align: right; padding: 6px 12px; border-bottom: 1px solid color-mix(in srgb, var(--border) 55%, transparent); white-space: nowrap; }
        .mbp-drv th { color: var(--text-muted); font-size: var(--fs-micro); font-weight: 600; position: sticky; top: 0; background: var(--bg-panel); }
        .mbp-drv th:first-child, .mbp-drv td:first-child { text-align: left; }
        .mbp-drv__key { max-width: 340px; overflow: hidden; text-overflow: ellipsis; }
        .mbp-drv__sf--absent { color: var(--text-muted); }
        .mbp .mbp-honesty { color: var(--text-muted); font-size: var(--fs-label); line-height: 1.5; margin: 16px 0 0; }
        .mbp-honesty b { color: var(--text-secondary); }
        .mono { font-family: var(--font-mono); }
      `}</style>
    </div>
  );
}
