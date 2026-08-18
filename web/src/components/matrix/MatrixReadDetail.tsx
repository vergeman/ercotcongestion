import { useEffect, useRef, useState, type ReactNode } from "react";
import type {
  AnalysisBasis,
  AnalysisConstraintRow,
  AnalysisContributionTerm,
  AnalysisNodeResponse,
  MatrixDamStatus,
  ReachSp,
} from "../../api/types";
import { getAnalysisNode } from "../../api/analysisNode";
import { fetchAnalysisEsspGroups } from "../../api/client";
import {
  ConstraintReachStyles,
  Dipole,
  dipoleCounts,
  useFullConstraintReach,
} from "../panels/ConstraintReach";
import BriefFootprintMap from "../brief/BriefFootprintMap";
import { mapLinkTo } from "../../lib/mapLinks";
import { shiftFactorColor } from "../../lib/colors";
import { constraintName, percent, usd, zoneLabel } from "../brief/briefFormat";
import type { MatrixEntitySelection, MatrixValTab } from "../../lib/matrix";

// The Matrix Read lens's detail (plan/0139-0003): a constraint's full SF reach
// (both dipole lobes, not a display top-k) or a node's full ranked driver
// column (not the bounded SF-grid rectangle). Reuses the genuinely
// selection-agnostic Brief pieces — the reach hook/glyphs
// (components/panels/ConstraintReach) and the footprint map — but does not
// reuse BriefDetailPanel's ConstraintEvidence/NodeEvidence: those render
// Brief's own pre-aggregated summary row (dominant driver, one μ peak) which
// this pane's data model doesn't have and deliberately goes beyond (the full
// column, every located member). History is left for 0004 — Matrix's
// full-vocabulary selections mostly fall outside Brief's own top-k, so there
// is no cheap, honest source for it yet.

interface Props {
  selection: MatrixEntitySelection;
  timestamp: Date | null;
  val: MatrixValTab;
  deliveryDate: string | null;
  runId: string | null;
  damStatus: MatrixDamStatus | null;
  constraintRow: AnalysisConstraintRow | null;
  nodeMeta: { type: string | null; zone: string | null } | null;
  onNavigateToMap: (search: string) => void;
}

function Fact({ label, value, tone }: { label: string; value: ReactNode; tone?: "pos" | "neg" }) {
  return (
    <div className="mrd-kv__row">
      <span className="mrd-kv__label">{label}</span>
      <span className={`mrd-kv__value${tone ? ` mrd-kv__value--${tone}` : ""}`}>{value}</span>
    </div>
  );
}

const LOBE_VISIBLE = 8;

function MemberRow({ sp }: { sp: ReachSp }) {
  return (
    <li className="cr-mem-row">
      <span className="cr-dot" style={{ background: shiftFactorColor(sp.sf) }} />
      <span className="cr-mem-sp mono">{sp.settlement_point}</span>
      <span className="cr-mem-sf mono" style={{ color: shiftFactorColor(sp.sf) }}>{sp.sf.toFixed(3)}</span>
    </li>
  );
}

function MemberLobe({ title, members }: { title: string; members: ReachSp[] }) {
  const visible = members.slice(0, LOBE_VISIBLE);
  const rest = members.slice(LOBE_VISIBLE);
  return (
    <div className="mrd-lobe">
      <h4>{title} <em>{members.length}</em></h4>
      {visible.length === 0
        ? <div className="cr-mem-msg">none located</div>
        : <ul className="cr-mem" role="list">{visible.map((sp) => <MemberRow key={sp.settlement_point} sp={sp} />)}</ul>}
      {rest.length > 0 && (
        <details className="mrd-lobe__tail">
          <summary>{rest.length} more</summary>
          <ul className="cr-mem" role="list">{rest.map((sp) => <MemberRow key={sp.settlement_point} sp={sp} />)}</ul>
        </details>
      )}
    </div>
  );
}

function ConstraintRead({
  selectionKey, row, onNavigateToMap,
}: { selectionKey: string; row: AnalysisConstraintRow | null; onNavigateToMap: (search: string) => void }) {
  const { reach, loading } = useFullConstraintReach(selectionKey);
  const { imp, exp } = dipoleCounts(reach);
  const name = constraintName(selectionKey);
  const contingency = selectionKey.includes("|") ? selectionKey.split("|")[1] : null;
  const mapHref = mapLinkTo({ kind: "constraint", value: selectionKey });

  const sps = reach?.sps ?? [];
  const importLobe = [...sps].filter((sp) => sp.sf < 0).sort((a, b) => a.sf - b.sf);
  const exportLobe = [...sps].filter((sp) => sp.sf >= 0).sort((a, b) => b.sf - a.sf);

  return (
    <>
      <div className="mrd__main">
        <header className="mrd__head">
          <span className="mrd__eyebrow">Constraint</span>
          <h2 className="mrd__title">{name}{contingency && <span className="mrd__contingency"> {contingency}</span>}</h2>
        </header>
        <div className="mrd-kv">
          <Fact label="Zone" value={zoneLabel(row?.zone ?? null)} />
          <Fact label="kV" value={row?.kv_max == null ? "—" : Math.round(row.kv_max)} />
          <Fact label="Type" value={row?.ctype ?? "—"} />
          <Fact label="Daily Σμ" value={row ? usd(row.daily_mu_sum, 2) : "—"} />
          <Fact label="Binding hours" value={row?.binding_hours ?? "—"} />
        </div>

        <div className="mrd-reach">
          <span className="mrd-section-title">
            Grid reach · import ↔ export{" "}
            {reach && !loading && <em>{reach.sps.length} located{reach.truncated ? " · truncated" : ""}</em>}
          </span>
          <div className="mrd-reach__dipole"><Dipole imp={imp} exp={exp} /></div>
          {loading ? (
            <div className="cr-mem-msg">loading members…</div>
          ) : (
            <div className="mrd-lobes">
              <MemberLobe title="Import · SF < 0" members={importLobe} />
              <MemberLobe title="Export · SF ≥ 0" members={exportLobe} />
            </div>
          )}
        </div>
      </div>
      <div className="mrd__map">
        <BriefFootprintMap selection={{ geo: "constraint", key: selectionKey }} mapHref={mapHref} onNavigate={onNavigateToMap} showTitle={false} />
      </div>
    </>
  );
}

function DriverRow({ term }: { term: AnalysisContributionTerm }) {
  const side = term.shift_factor >= 0 ? "export" : "import";
  const mu = term.shift_factor !== 0 ? -term.contribution / term.shift_factor : null;
  return (
    <tr>
      <td className="mrd-drv__key mono">{constraintName(term.constraint_key)}</td>
      <td className="mono" style={{ color: shiftFactorColor(term.shift_factor) }}>{term.shift_factor.toFixed(3)}</td>
      <td className="mrd-drv__side">{side}</td>
      <td className="mono">{mu == null ? "—" : usd(mu, 0)}</td>
      <td className={`mono${term.contribution >= 0 ? " mrd-kv__value--pos" : " mrd-kv__value--neg"}`}>{usd(term.contribution, 2)}</td>
    </tr>
  );
}

function NodeRead({
  point, meta, timestamp, val, deliveryDate, runId, damStatus, onNavigateToMap,
}: {
  point: string;
  meta: { type: string | null; zone: string | null } | null;
  timestamp: Date | null;
  val: MatrixValTab;
  deliveryDate: string | null;
  runId: string | null;
  damStatus: MatrixDamStatus | null;
  onNavigateToMap: (search: string) => void;
}) {
  const basis: AnalysisBasis = val === "dmu" ? "realized" : "predicted";
  // DAM-unavailable must stay unavailable, never a fabricated zero: block the
  // fetch outright rather than trust the caller already guarded `val`.
  const damPendingBlock = basis === "realized" && damStatus === "pending";
  const [node, setNode] = useState<AnalysisNodeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [esspCount, setEsspCount] = useState<number | null>(null);
  const requestId = useRef(0);

  useEffect(() => {
    if (!timestamp || !deliveryDate || damPendingBlock) { setNode(null); setLoading(false); return; }
    const controller = new AbortController();
    const id = ++requestId.current;
    setLoading(true);
    getAnalysisNode(point, deliveryDate, timestamp.toISOString(), basis, runId ?? undefined, controller.signal)
      .then((response) => { if (id === requestId.current) setNode(response); })
      .catch((error: unknown) => {
        if (error instanceof Error && error.name === "AbortError") return;
        if (id === requestId.current) setNode(null);
      })
      .finally(() => { if (id === requestId.current) setLoading(false); });
    return () => controller.abort();
  }, [point, deliveryDate, timestamp, basis, runId, damPendingBlock]);

  useEffect(() => {
    if (!timestamp) { setEsspCount(null); return; }
    let live = true;
    fetchAnalysisEsspGroups(timestamp.toISOString())
      .then((response) => {
        if (!live || !response.available) { if (live) setEsspCount(null); return; }
        const group = response.groups?.find((g) => g.settlement_points.includes(point));
        setEsspCount(group ? group.settlement_points.length : null);
      })
      .catch(() => { if (live) setEsspCount(null); });
    return () => { live = false; };
  }, [point, timestamp]);

  const mapHref = mapLinkTo({ kind: "sp", value: point });
  const terms = node?.available ? node.terms ?? [] : [];

  return (
    <>
      <div className="mrd__main">
        <header className="mrd__head">
          <span className="mrd__eyebrow">Settlement point</span>
          <h2 className="mrd__title">{point}</h2>
        </header>
        <div className="mrd-kv">
          <Fact label="Zone" value={zoneLabel(meta?.zone ?? null)} />
          <Fact label="Type" value={meta?.type ?? "—"} />
          {esspCount != null && esspCount > 1 && <Fact label="ESSP members" value={`≈${esspCount}`} />}
        </div>

        {damPendingBlock && (
          <div className="mrd-notice">ERCOT DAM μ has not been published for this delivery day — unavailable, not zero.</div>
        )}
        {!damPendingBlock && basis === "realized" && damStatus === "partial" && (
          <div className="mrd-notice">ERCOT DAM μ is only partially published for this day; unmatched constraints read as zero here.</div>
        )}
        {!damPendingBlock && loading && !node && <div className="mrd-loading">Loading node column…</div>}
        {!damPendingBlock && !loading && node && !node.available && (
          <div className="mrd-notice">No forecast artifact for this node on this delivery day.</div>
        )}
        {!damPendingBlock && node?.available && (
          <>
            <div className="mrd-kv mrd-kv--stats">
              <Fact
                label={basis === "realized" ? "DAM 7×16 $/MWh" : "Forecast 7×16 $/MWh"}
                value={usd(node.total ?? 0, 2)}
                tone={(node.total ?? 0) >= 0 ? "pos" : "neg"}
              />
              <Fact label="SF coverage" value={node.coverage == null ? "—" : percent(node.coverage)} />
              <Fact label="Drivers" value={`${node.n_terms ?? terms.length} of the artifact's constraints`} />
            </div>
            <div className="mrd-drivers">
              <span className="mrd-section-title">Congestion drivers <em>full column · −SF·μ</em></span>
              <table className="mrd-drv">
                <thead><tr><th>constraint</th><th>SF</th><th>side</th><th>μ</th><th>$/MWh</th></tr></thead>
                <tbody>{terms.map((term) => <DriverRow key={term.constraint_key} term={term} />)}</tbody>
              </table>
            </div>
          </>
        )}
      </div>
      <div className="mrd__map">
        <BriefFootprintMap selection={{ geo: "node", key: point }} mapHref={mapHref} onNavigate={onNavigateToMap} showTitle={false} />
      </div>
    </>
  );
}

export default function MatrixReadDetail({
  selection, timestamp, val, deliveryDate, runId, damStatus, constraintRow, nodeMeta, onNavigateToMap,
}: Props) {
  if (!selection) {
    return <div className="mrd mrd--empty">Select a constraint or node from the index to see its evidence.</div>;
  }
  return (
    <div className="mrd">
      <ConstraintReachStyles />
      {selection.kind === "constraint"
        ? <ConstraintRead selectionKey={selection.key} row={constraintRow} onNavigateToMap={onNavigateToMap} />
        : <NodeRead point={selection.point} meta={nodeMeta} timestamp={timestamp} val={val} deliveryDate={deliveryDate} runId={runId} damStatus={damStatus} onNavigateToMap={onNavigateToMap} />}
      <style>{`
        /* Two columns: a scrolling evidence column on the left and the grid
           footprint pinned full-height on the right. The pane's own
           .matrix-workspace__read container owns the height; the left column
           scrolls within it while the map stays put. */
        .mrd { height: 100%; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 0; }
        .mrd--empty { color: var(--text-secondary); display: grid; place-items: center; padding: 40px 20px; text-align: center; }
        .mrd__main { min-width: 0; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 4px 20px 24px 2px; }
        .mrd__map { min-width: 0; border-left: 1px solid var(--border); padding-left: 18px; }
        /* Fill the column height with the footprint, overriding the Brief
           default's fixed aspect box — the map centres (xMidYMid meet) inside. */
        .mrd__map .bfm { margin: 0; height: 100%; display: flex; flex-direction: column; }
        .mrd__map .bfm__frame { flex: 1; min-height: 0; margin-top: 0; }
        .mrd__map .bfm__svg { height: 100%; }
        .mrd__head { margin-bottom: 12px; }
        .mrd__title { margin: 2px 0 0; font-family: var(--font-mono); font-size: var(--fs-xl); line-height: 1.2; overflow-wrap: anywhere; }
        .mrd__eyebrow { color: var(--text-secondary); font: 600 var(--fs-xs) var(--font-label); letter-spacing: var(--track-label); text-transform: uppercase; }
        .mrd__contingency { color: var(--text-muted); font-weight: 400; }
        .mrd-section-title { display: block; margin-bottom: 8px; color: var(--text-secondary); font: 600 var(--fs-md) var(--font-label); letter-spacing: var(--track-label); text-transform: uppercase; }
        .mrd-section-title em { font-style: normal; color: var(--text-muted); text-transform: none; }
        .mrd-kv { display: flex; flex-direction: column; margin: 0 0 4px; }
        .mrd-kv--stats { margin-top: 16px; }
        @media (max-width: 760px) {
          .mrd { grid-template-columns: 1fr; height: auto; }
          .mrd__main { overflow-y: visible; padding-right: 2px; }
          .mrd__map { border-left: 0; border-top: 1px solid var(--border); padding-left: 0; padding-top: 16px; margin-top: 4px; height: 320px; }
        }
        .mrd-kv__row { display: flex; gap: 14px; align-items: baseline; padding: 5px 0; border-bottom: 1px solid color-mix(in srgb, var(--border) 60%, transparent); }
        .mrd-kv__row:last-child { border-bottom: 0; }
        .mrd-kv__label { flex: 0 0 140px; color: var(--text-muted); font-size: var(--fs-label); }
        .mrd-kv__value { flex: 1 1 auto; min-width: 0; color: var(--text-primary); font-family: var(--font-mono); font-size: var(--fs-md); overflow-wrap: anywhere; }
        .mrd-kv__value--pos { color: var(--danger, #d94444); }
        .mrd-kv__value--neg { color: var(--accent); }
        .mrd-notice, .mrd-loading { margin-top: 14px; padding: 8px 10px; border: 1px solid var(--border); background: var(--accent-dim); color: var(--text-secondary); font-size: var(--fs-label); }
        .mrd-reach, .mrd-drivers { margin-top: 22px; padding-top: 22px; border-top: 1px solid var(--border); }
        .mrd-reach__dipole { width: 100%; margin: 8px 0 10px; }
        .mrd-lobes { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
        .mrd-lobe h4 { margin: 0 0 6px; font-size: var(--fs-label); color: var(--text-secondary); font-weight: 600; }
        .mrd-lobe h4 em { font-style: normal; color: var(--text-muted); }
        .mrd-lobe__tail { margin-top: 4px; }
        .mrd-lobe__tail summary { color: var(--accent); cursor: pointer; font-size: var(--fs-micro); padding: 4px 2px; }
        .mrd-drv { width: 100%; border-collapse: collapse; font-size: var(--fs-label); }
        .mrd-drv th, .mrd-drv td { text-align: right; padding: 5px 8px; border-bottom: 1px solid color-mix(in srgb, var(--border) 55%, transparent); }
        .mrd-drv th { color: var(--text-muted); font-size: var(--fs-micro); text-transform: uppercase; letter-spacing: .04em; font-weight: 600; }
        .mrd-drv th:first-child, .mrd-drv td:first-child { text-align: left; }
        .mrd-drv__key { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .mrd-drv__side { color: var(--text-muted); }
        @media (max-width: 900px) { .mrd-lobes { grid-template-columns: 1fr; } }
      `}</style>
    </div>
  );
}
