/* eslint-disable react-hooks/set-state-in-effect */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type {
  AnalysisBasis,
  AnalysisConstraintRow,
  AnalysisContributionTerm,
  AnalysisNodeResponse,
  ConstraintReach,
  MatrixDamStatus,
  ReachSp,
} from "../../api/types";
import { getAnalysisNode } from "../../api/analysisNode";
import {
  ConstraintReachStyles,
  Dipole,
  dipoleCounts,
  REACH_K,
  useFullConstraintReach,
} from "../panels/ConstraintReach";
import { REACH_THRESHOLD_OPTS } from "../../api/client";
import MiniMap from "../map/MiniMap";
import { mapLinkTo } from "../../lib/mapLinks";
import { shiftFactorColor } from "../../lib/colors";
import {
  constraintName,
  marketValue,
  percent,
  usd,
  zoneLabel,
} from "../../lib/format";
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
  damStatus: MatrixDamStatus | null;
  constraintRow: AnalysisConstraintRow | null;
  nodeMeta: {
    type: string | null;
    zone: string | null;
    lat: number | null;
    lon: number | null;
  } | null;
  onNavigateToMap: (search: string) => void;
}

function Fact({
  label,
  value,
  tone,
  numeric = false,
}: {
  label: string;
  value: ReactNode;
  tone?: "pos" | "neg";
  numeric?: boolean;
}) {
  return (
    <div className="mrd-kv__row">
      <span className="mrd-kv__label">{label}</span>
      <span
        className={`mrd-kv__value${tone ? ` mrd-kv__value--${tone}` : ""}${
          numeric ? " mrd-kv__value--numeric" : ""
        }`}
      >
        {value}
      </span>
    </div>
  );
}

function DetailSummary({
  hourly,
  structural,
}: {
  hourly: ReactNode;
  structural: ReactNode;
}) {
  return (
    <div className="mrd-summary">
      <section className="mrd-summary__section" aria-label="Selected hour">
        <span className="mrd-section-title">Selected hour</span>
        <div className="mrd-kv">{hourly}</div>
      </section>
      <section
        className="mrd-summary__section"
        aria-label="Daily and structural evidence"
      >
        <span className="mrd-section-title">Daily / structural</span>
        <div className="mrd-kv">{structural}</div>
      </section>
    </div>
  );
}

const LOBE_VISIBLE = 8;

function MemberRow({ sp }: { sp: ReachSp }) {
  return (
    <li className="cr-mem-row">
      <span
        className="cr-dot"
        style={{ background: shiftFactorColor(sp.sf) }}
      />
      <span className="cr-mem-sp mono">{sp.settlement_point}</span>
      <span
        className="cr-mem-sf mono"
        style={{ color: shiftFactorColor(sp.sf) }}
      >
        {sp.sf.toFixed(3)}
      </span>
    </li>
  );
}

function MemberLobe({ title, members }: { title: string; members: ReachSp[] }) {
  const visible = members.slice(0, LOBE_VISIBLE);
  const rest = members.slice(LOBE_VISIBLE);
  return (
    <div className="mrd-lobe">
      <h4>
        {title} <em>{members.length}</em>
      </h4>
      {visible.length === 0 ? (
        <div className="cr-mem-msg">none located</div>
      ) : (
        <ul className="cr-mem" role="list">
          {visible.map((sp) => (
            <MemberRow key={sp.settlement_point} sp={sp} />
          ))}
        </ul>
      )}
      {rest.length > 0 && (
        <details className="mrd-lobe__tail">
          <summary>{rest.length} more</summary>
          <ul className="cr-mem" role="list">
            {rest.map((sp) => (
              <MemberRow key={sp.settlement_point} sp={sp} />
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function footprintReach(reach: ConstraintReach | null) {
  if (!reach) return reach;
  const floor = Math.max(
    (REACH_THRESHOLD_OPTS.minFrac ?? 0) * (reach.max_abs_sf ?? 0),
    REACH_THRESHOLD_OPTS.absFloor ?? 0
  );
  return {
    ...reach,
    sps: reach.sps.filter((sp) => Math.abs(sp.sf) >= floor).slice(0, REACH_K),
  };
}

function ConstraintRead({
  selectionKey,
  row,
  timestamp,
  onNavigateToMap,
}: {
  selectionKey: string;
  row: AnalysisConstraintRow | null;
  timestamp: Date | null;
  onNavigateToMap: (search: string) => void;
}) {
  // The scrubbed interval selects the CT delivery day whose artifact backs the
  // reach (0144) — the same day the rest of the Read pane describes.
  const cursorTs = timestamp ?? undefined;
  const { reach, loading } = useFullConstraintReach(selectionKey, cursorTs);
  const { imp, exp } = dipoleCounts(reach);
  const name = constraintName(selectionKey);
  const contingency = selectionKey.includes("|")
    ? selectionKey.split("|")[1]
    : null;
  const mapHref = mapLinkTo({ kind: "constraint", value: selectionKey });

  const sps = reach?.sps ?? [];
  const mapReach = useMemo(() => footprintReach(reach), [reach]);
  const importLobe = [...sps]
    .filter((sp) => sp.sf < 0)
    .sort((a, b) => a.sf - b.sf);
  const exportLobe = [...sps]
    .filter((sp) => sp.sf >= 0)
    .sort((a, b) => b.sf - a.sf);

  return (
    <>
      <div className="mrd__main">
        <header className="mrd__head">
          <span className="mrd__eyebrow">Constraint</span>
          <h2 className="mrd__title">
            {name}
            {contingency && (
              <span className="mrd__contingency"> {contingency}</span>
            )}
          </h2>
        </header>
        <DetailSummary
          hourly={
            <>
              <Fact
                label="Forecast μ"
                value={marketValue(reach?.shadow_price)}
                numeric
              />
              <Fact label="DAM μ" value={marketValue(reach?.dam_mu)} numeric />
              <Fact
                label="Forecast Error"
                value={marketValue(reach?.forecast_error)}
                numeric
              />
            </>
          }
          structural={
            <>
              <Fact
                label="Forecast μ rank"
                value={reach?.daily_mu_rank ?? row?.daily_mu_rank ?? "—"}
                numeric
              />
              <Fact
                label="Daily Σμ"
                value={
                  reach?.daily_mu_sum == null
                    ? row
                      ? usd(row.daily_mu_sum, 2)
                      : "—"
                    : usd(reach.daily_mu_sum, 2)
                }
                numeric
              />
              <Fact
                label="Binding hours"
                value={reach?.binding_hours ?? row?.binding_hours ?? "—"}
                numeric
              />
              <Fact
                label="Peak |SF|"
                value={
                  reach?.max_abs_sf == null ? "—" : reach.max_abs_sf.toFixed(3)
                }
                numeric
              />
              <Fact
                label="Import / export"
                value={
                  reach
                    ? `${reach.import_members ?? imp} / ${
                        reach.export_members ?? exp
                      }`
                    : "—"
                }
                numeric
              />
              <Fact label="Zone" value={zoneLabel(row?.zone ?? null)} numeric />
              <Fact
                label="kV"
                value={row?.kv_max == null ? "—" : Math.round(row.kv_max)}
                numeric
              />
            </>
          }
        />

        <div className="mrd-reach">
          <span className="mrd-section-title">
            Grid reach · import ↔ export{" "}
            {reach && !loading && (
              <em>
                {reach.sps.length} located
                {reach.truncated ? " · truncated" : ""}
              </em>
            )}
          </span>
          <div className="mrd-reach__dipole">
            <Dipole imp={imp} exp={exp} />
          </div>
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
        <MiniMap
          mode="constraint"
          selectionKey={selectionKey}
          mapHref={mapHref}
          onNavigate={onNavigateToMap}
          showTitle={false}
          t={cursorTs}
          reach={mapReach}
          reachLoading={loading}
        />
      </div>
    </>
  );
}

// A constraint's shadow price this hour, backed out of −SF·μ. Null when the SF
// is zero (no relationship to divide through).
function termMu(term: AnalysisContributionTerm): number | null {
  return term.shift_factor !== 0 ? -term.contribution / term.shift_factor : null;
}

// The node table's sortable columns. Default is $/MWh (driver strength), so the
// table opens as the drivers list; sort by SF for structural exposure, and the
// `*` on a capped SF flags what the fit could not trust.
type NodeSortKey = "sf" | "side" | "mu" | "contribution" | "binding";
interface NodeSort {
  key: NodeSortKey;
  dir: "asc" | "desc";
}

const NODE_COLUMNS: Array<{ key: NodeSortKey; label: string; title: string }> = [
  { key: "binding", label: "bind", title: "Hours the constraint bound on the delivery day." },
  { key: "side", label: "side", title: "Import (SF<0) or export (SF≥0)." },
  { key: "sf", label: "SF", title: "Implied shift factor; sorts by |SF|. * = pinned at the fit's clip." },
  { key: "mu", label: "μ", title: "Constraint shadow price this hour ($/MWh)." },
  { key: "contribution", label: "$/MWh", title: "This node's congestion from the constraint (−SF·μ); sorts by magnitude." },
];

// Bigger sorts first under descending. SF and $/MWh key off magnitude (the
// driver/exposure strength); side keys off the SF sign so imports and exports
// group together.
function nodeSortValue(term: AnalysisContributionTerm, key: NodeSortKey): number {
  switch (key) {
    case "sf": return Math.abs(term.shift_factor);
    case "side": return Math.sign(term.shift_factor);
    case "mu": return termMu(term) ?? -Infinity;
    case "contribution": return Math.abs(term.contribution);
    case "binding": return term.binding_hours;
  }
}

function nodeDefaultDir(key: NodeSortKey): "asc" | "desc" {
  return key === "side" ? "asc" : "desc";
}

function DriverRow({ term }: { term: AnalysisContributionTerm }) {
  const side = term.shift_factor >= 0 ? "export" : "import";
  const mu = termMu(term);
  return (
    <tr>
      <td className="mrd-drv__key mono">
        {constraintName(term.constraint_key)}
      </td>
      <td className="mono">{term.binding_hours}h</td>
      <td className="mrd-drv__side">{side}</td>
      <td
        className="mono"
        style={{ color: shiftFactorColor(term.shift_factor) }}
      >
        {term.shift_factor.toFixed(3)}
        {term.sf_clipped && <span className="mrd-drv__clip">*</span>}
      </td>
      <td className="mono">{mu == null ? "—" : usd(mu, 2)}</td>
      <td
        className={`mono${
          term.contribution >= 0 ? " mrd-kv__value--pos" : " mrd-kv__value--neg"
        }`}
      >
        {usd(term.contribution, 2)}
      </td>
    </tr>
  );
}

// One sortable table over the node's full nonzero-SF set — it replaces the old
// drivers table plus the separate structural-exposure disclosure. Sort by $/MWh
// (default) for the drivers, by SF for structural exposure, by bind/clip to spot
// what is not structurally sound.
function DriverTable({
  terms,
  sort,
  onToggleSort,
}: {
  terms: AnalysisContributionTerm[];
  sort: NodeSort;
  onToggleSort: (key: NodeSortKey) => void;
}) {
  const rows = useMemo(() => {
    const sign = sort.dir === "asc" ? 1 : -1;
    return [...terms].sort(
      (a, b) => sign * (nodeSortValue(a, sort.key) - nodeSortValue(b, sort.key))
    );
  }, [terms, sort]);
  const clipped = rows.some((t) => t.sf_clipped);
  return (
    <>
      <table className="mrd-drv">
        <thead>
          <tr>
            <th>constraint</th>
            {NODE_COLUMNS.map((c) => {
              const active = sort.key === c.key;
              return (
                <th
                  key={c.key}
                  className={`mrd-drv__sort${active ? " is-active" : ""}`}
                  title={c.title}
                  tabIndex={0}
                  aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
                  onClick={() => onToggleSort(c.key)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onToggleSort(c.key);
                    }
                  }}
                >
                  {c.label}
                  {active ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((term) => (
            <DriverRow key={term.constraint_key} term={term} />
          ))}
        </tbody>
      </table>
      {clipped && (
        <div className="mrd-drv__note">
          * SF pinned at the fit's ±1 clip — a bound, not a measurement
        </div>
      )}
    </>
  );
}


function NodeRead({
  point,
  meta,
  timestamp,
  val,
  deliveryDate,
  damStatus,
  sort,
  onToggleSort,
  onNavigateToMap,
}: {
  point: string;
  meta: {
    type: string | null;
    zone: string | null;
    lat: number | null;
    lon: number | null;
  } | null;
  timestamp: Date | null;
  val: MatrixValTab;
  deliveryDate: string | null;
  damStatus: MatrixDamStatus | null;
  sort: NodeSort;
  onToggleSort: (key: NodeSortKey) => void;
  onNavigateToMap: (search: string) => void;
}) {
  const basis: AnalysisBasis = val === "dmu" ? "realized" : "predicted";
  const [node, setNode] = useState<AnalysisNodeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const requestId = useRef(0);

  useEffect(() => {
    if (!timestamp || !deliveryDate) {
      setNode(null);
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    const id = ++requestId.current;
    setNode(null);
    setLoading(true);
    getAnalysisNode(
      point,
      deliveryDate,
      timestamp.toISOString(),
      basis,
      controller.signal,
      true
    )
      .then((response) => {
        if (id === requestId.current) setNode(response);
      })
      .catch((error: unknown) => {
        if (error instanceof Error && error.name === "AbortError") return;
        if (id === requestId.current) setNode(null);
      })
      .finally(() => {
        if (id === requestId.current) {
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [point, deliveryDate, timestamp, basis]);

  const mapHref = mapLinkTo({ kind: "sp", value: point });
  const terms = node?.available ? node.terms ?? [] : [];
  const structuralTerms = node?.available ? node.structural_terms ?? [] : [];
  // One table over the full nonzero-SF set when we have it (it is the superset
  // that includes the drivers), else the drivers alone.
  const tableTerms = structuralTerms.length > 0 ? structuralTerms : terms;
  const market = node?.available ? node.market_state : null;

  return (
    <>
      <div className="mrd__main">
        <header className="mrd__head">
          <span className="mrd__eyebrow">Settlement point</span>
          <h2 className="mrd__title">{point}</h2>
        </header>
        {node?.available && (
          <DetailSummary
            hourly={
              <>
                <Fact
                  label="Forecast Congestion"
                  value={marketValue(market?.forecast_congestion)}
                  numeric
                />
                <Fact
                  label="Realized Congestion"
                  value={marketValue(market?.realized_congestion)}
                  numeric
                />
                <Fact
                  label="Forecast Error"
                  value={marketValue(market?.forecast_error)}
                  numeric
                />
                <Fact
                  label="Forecast LMP"
                  value={marketValue(market?.forecast_lmp)}
                  numeric
                />
                <Fact
                  label="DAM LMP"
                  value={marketValue(market?.dam_lmp)}
                  numeric
                />
                <Fact
                  label={
                    basis === "realized"
                      ? "DAM μ attribution"
                      : "Forecast μ attribution"
                  }
                  value={marketValue(node.total)}
                  tone={(node.total ?? 0) >= 0 ? "pos" : "neg"}
                  numeric
                />
              </>
            }
            structural={
              <>
                <Fact
                  label="Zone"
                  value={zoneLabel(meta?.zone ?? null)}
                  numeric
                />
                <Fact label="Type" value={meta?.type ?? "—"} numeric />
                <Fact
                  label="ESSP members"
                  value={
                    node.essp_member_count != null && node.essp_member_count > 1
                      ? `≈${node.essp_member_count}`
                      : "—"
                  }
                  numeric
                />
                <Fact
                  label="SF coverage"
                  value={node.coverage == null ? "—" : percent(node.coverage)}
                  numeric
                />
                <Fact
                  label="Current drivers"
                  value={`${node.n_terms ?? terms.length}`}
                  numeric
                />
              </>
            }
          />
        )}

        {basis === "realized" && node?.available && market?.dam_lmp == null && (
          <div className="mrd-notice">
            ERCOT DAM LMP has not been published for this settlement point and
            hour — unavailable, not zero.
          </div>
        )}
        {basis === "realized" && damStatus === "partial" && (
          <div className="mrd-notice">
            ERCOT DAM μ is only partially published for this day; unmatched
            constraints read as zero here.
          </div>
        )}
        {loading && !node && (
          <div className="mrd-loading">Loading node column…</div>
        )}
        {!loading && node && !node.available && (
          <div className="mrd-notice">
            No forecast artifact for this node on this delivery day.
          </div>
        )}
        {node?.available && tableTerms.length > 0 && (
          <div className="mrd-drivers">
            <span className="mrd-section-title">
              Drivers &amp; exposure{" "}
              <em>
                {`${node.structural_n_terms ?? tableTerms.length} constraints · −SF·μ · sort any column`}
              </em>
            </span>
            <DriverTable terms={tableTerms} sort={sort} onToggleSort={onToggleSort} />
          </div>
        )}
      </div>
      <div className="mrd__map">
        <MiniMap
          mode="node"
          selectionKey={point}
          mapHref={mapHref}
          onNavigate={onNavigateToMap}
          showTitle={false}
          nodeLocation={
            meta?.lat != null && meta.lon != null
              ? { lat: meta.lat, lng: meta.lon }
              : null
          }
        />
      </div>
    </>
  );
}

export default function MatrixReadDetail({
  selection,
  timestamp,
  val,
  deliveryDate,
  damStatus,
  constraintRow,
  nodeMeta,
  onNavigateToMap,
}: Props) {
  // The node table's sort lives here, above NodeRead, so it survives switching
  // between nodes (NodeRead and its table remount, but this frame stays).
  const [nodeSort, setNodeSort] = useState<NodeSort>({
    key: "contribution",
    dir: "desc",
  });
  const toggleNodeSort = (key: NodeSortKey) =>
    setNodeSort((cur) =>
      cur.key === key
        ? { key, dir: cur.dir === "asc" ? "desc" : "asc" }
        : { key, dir: nodeDefaultDir(key) }
    );

  if (!selection) {
    return (
      <div className="mrd mrd--empty">
        Select a constraint or node from the index to see its evidence.
      </div>
    );
  }
  return (
    <div className="mrd">
      <ConstraintReachStyles />
      {selection.kind === "constraint" ? (
        <ConstraintRead
          selectionKey={selection.key}
          row={constraintRow}
          timestamp={timestamp}
          onNavigateToMap={onNavigateToMap}
        />
      ) : (
        <NodeRead
          point={selection.point}
          meta={nodeMeta}
          timestamp={timestamp}
          val={val}
          deliveryDate={deliveryDate}
          damStatus={damStatus}
          sort={nodeSort}
          onToggleSort={toggleNodeSort}
          onNavigateToMap={onNavigateToMap}
        />
      )}
      <style>{`
        /* Two columns: a scrolling evidence column on the left and the grid
           footprint pinned full-height on the right. The pane's own
           .matrix-workspace__read container owns the height; the left column
           scrolls within it while the map stays put. */
        .mrd { --mrd-fact-label: 216px; --mrd-fact-value: 130px; height: 100%; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 0; }
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
        /* A compact facts table: every label and value shares the same two
           columns, while numeric values can right-align without drifting to
           the far side of the Detail pane. */
        .mrd-kv { display: grid; width: 100%; margin: 0 0 4px; }
        .mrd-summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; margin-bottom: 4px; }
        .mrd-summary__section { min-width: 0; }
        .mrd-summary .mrd-section-title { padding-bottom: 8px; border-bottom: 1px solid var(--border); }
        .mrd-summary .mrd-kv__row { grid-template-columns: minmax(0, 1fr) 112px; gap: 10px; }
        @media (max-width: 760px) {
          .mrd { grid-template-columns: 1fr; height: auto; }
          .mrd__main { overflow-y: visible; padding-right: 2px; }
          .mrd__map { border-left: 0; border-top: 1px solid var(--border); padding-left: 0; padding-top: 16px; margin-top: 4px; height: 320px; }
          .mrd-summary { grid-template-columns: 1fr; gap: 18px; }
        }
        .mrd-kv__row { display: grid; grid-template-columns: minmax(0, var(--mrd-fact-label)) var(--mrd-fact-value) minmax(0, 1fr); gap: 14px; align-items: baseline; padding: 5px 0; border-bottom: 1px solid color-mix(in srgb, var(--border) 60%, transparent); }
        .mrd-kv__row:last-child { border-bottom: 0; }
        .mrd-kv__label { min-width: 0; color: var(--text-muted); font-size: var(--fs-label); }
        .mrd-kv__value { min-width: 0; color: var(--text-primary); font-family: var(--font-mono); font-size: var(--fs-md); overflow-wrap: anywhere; }
        .mrd-kv__value--numeric { text-align: right; font-variant-numeric: tabular-nums; }
        @media (max-width: 440px) { .mrd-kv__row { grid-template-columns: minmax(0, 1fr) minmax(120px, 150px); } }
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
        .mrd-drv__clip { color: var(--text-muted); padding-left: 1px; }
        /* Clickable sort headers keep the header look, gaining a pointer and an
           accent when active. */
        .mrd-drv th.mrd-drv__sort { cursor: pointer; user-select: none; white-space: nowrap; }
        .mrd-drv th.mrd-drv__sort:hover { color: var(--text-secondary); }
        .mrd-drv th.mrd-drv__sort.is-active { color: var(--accent); }
        .mrd-drv__note { margin-top: 8px; color: var(--text-muted); font-size: var(--fs-micro); }
        @media (max-width: 900px) { .mrd-lobes { grid-template-columns: 1fr; } }
      `}</style>
    </div>
  );
}
