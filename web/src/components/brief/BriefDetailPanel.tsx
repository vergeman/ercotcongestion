import { useEffect, useRef, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type {
  NodeStandoutRow,
  StandoutRow,
  TopConstraintRow,
  TopNodeRow,
} from "../../api/types";
import {
  briefElementMapHref,
  selectionGeo,
  selectionKey,
  type BriefSelection,
} from "../../lib/briefSelection";
import {
  HistoryBars,
  HistoryWhisker,
  constraintName,
  percent,
  rankMovement,
  usd,
  zoneLabel,
} from "./briefFormat";
import {
  ConstraintReachStyles,
  Dipole,
  MemberList,
  SfDipoleLegend,
  dipoleCounts,
  useConstraintReach,
} from "../panels/ConstraintReach";

// One shared sliding detail panel for every selectable Brief row (plan/0135). A
// row is an inspection action, not a link: clicking it opens this right-side
// dialog over the same delivery day, shows the evidence behind the ranking, and
// offers a *deliberate* handoff to the full Map — the `/map` link that used to
// live on the row itself now lives here.
//
// The panel is a controlled overlay: `selection` non-null means open. It never
// rewrites the Brief's `?t/?ws/?we` time coordinate — opening and closing is
// pure UI state. Evidence honours the mode 0009 already selected (`settled`):
// settled columns are shown only once DAM has settled, never a second
// availability decision here.
//
// Deliberately NOT a second Map: no ExplorerLayout / scrubber / MapWorkspace
// (plan/0135). The abstract footprint (a later pass) is orientation only.

interface Props {
  selection: BriefSelection | null;
  settled: boolean;
  heroCursor: { t: string; ws: string; we: string } | null | undefined;
  onClose: () => void;
}

const TITLE_ID = "brief-detail-title";

// A labelled figure in the evidence grid. `tone` colors node dollars by sign the
// way the tables do; a missing value renders an em dash, never a fabricated 0.
function Fact({
  label,
  value,
  tone,
}: {
  label: string;
  value: ReactNode;
  tone?: "positive" | "negative";
}) {
  return (
    <div className="bdp-fact">
      <span className="bdp-fact__label">{label}</span>
      <span
        className={
          tone === "positive"
            ? "bdp-fact__value bdp-fact__value--pos"
            : tone === "negative"
            ? "bdp-fact__value bdp-fact__value--neg"
            : "bdp-fact__value"
        }
      >
        {value}
      </span>
    </div>
  );
}

function dollarTone(value: number | null | undefined) {
  if (value == null) return undefined;
  return value >= 0 ? "positive" : ("negative" as const);
}

// The trailing-30-day block (whisker + per-day bars) shared by every kind, with
// the mark placed on the settled total once settled, else the forecast total.
function HistoryBlock({
  low,
  q25,
  median,
  q75,
  high,
  mark,
  values,
  unit,
}: {
  low: number | null;
  q25: number | null;
  median: number | null;
  q75: number | null;
  high: number | null;
  mark: number | null;
  values: number[];
  unit: string;
}) {
  return (
    <div className="bdp-history">
      <span className="bdp-fact__label">
        {unit} vs its own 30 days · each of 30 days
      </span>
      <div className="bdp-history__glyphs">
        <HistoryWhisker
          low={low}
          q25={q25}
          median={median}
          q75={q75}
          high={high}
          mark={mark}
        />
        <HistoryBars values={values} />
      </div>
    </div>
  );
}

const STANDOUT_CONSTRAINT_KIND: Record<string, string> = {
  forecast_elevated: "Forecast runs hot vs its own 30-day history",
  chronic_under_called: "Chronically binds but the forecast is quiet",
  settled_elevated: "Settled elevated — not flagged before the day",
};
const STANDOUT_NODE_KIND: Record<string, string> = {
  forecast_elevated: "Forecast runs hot vs its own 30-day history",
  forecast_depressed: "Forecast runs cold vs its own 30-day history",
  settled_elevated: "Settled elevated — not flagged before the day",
};

function ConstraintEvidence({
  row,
  settled,
  standout,
}: {
  // Both constraint schemas carry every field this reads; they differ only in
  // nullability, so the union widens the numeric cells to `number | null` — which
  // the em-dash guards below already handle.
  row: StandoutRow | TopConstraintRow;
  settled: boolean;
  standout: StandoutRow | null;
}) {
  // The constraint's SF reach — the located member nodes it drives and the
  // import↔export dipole they form — is the same evidence the map's Constraints
  // sidebar shows; both read it through the shared reach hook/cache.
  const { reach, loading } = useConstraintReach(row.constraint_key);
  const { imp, exp } = dipoleCounts(reach);
  return (
    <>
      <div className="bdp-grid">
        <Fact label="Zone" value={zoneLabel(row.zone)} />
        <Fact label="kV" value={row.kv_max == null ? "—" : Math.round(row.kv_max)} />
        <Fact
          label="Forecast rank"
          value={row.forecast_rank ?? "—"}
        />
        <Fact
          label="Forecast μ peak"
          value={row.forecast_peak == null ? "—" : usd(row.forecast_peak, 2)}
        />
        <Fact
          label="Forecast Σμ $/MW"
          value={row.forecast_total == null ? "—" : usd(row.forecast_total, 2)}
        />
        <Fact label="Forecast hrs bind" value={row.forecast_hours ?? "—"} />
        {settled && (
          <>
            <Fact
              label="DAM rank"
              value={rankMovement(row.forecast_rank, row.settled_rank ?? null)}
            />
            <Fact
              label="DAM μ peak"
              value={row.settled_peak == null ? "—" : usd(row.settled_peak, 2)}
            />
            <Fact
              label="DAM Σμ $/MW"
              value={
                row.settled_total == null ? "—" : usd(row.settled_total, 2)
              }
            />
            <Fact label="DAM hrs bind" value={row.settled_hours ?? "—"} />
          </>
        )}
      </div>
      {standout && (
        <div className="bdp-why">
          <span className="bdp-fact__label">Why it stood out</span>
          <p>{STANDOUT_CONSTRAINT_KIND[standout.kind] ?? standout.kind}</p>
          <div className="bdp-grid bdp-grid--why">
            <Fact
              label="Σμ, today"
              value={usd(standout.forecast_total, 2)}
            />
            <Fact
              label="Σμ, 30-day median"
              value={usd(standout.forecast_history_median, 2)}
            />
            <Fact
              label="History days"
              value={standout.forecast_history_days}
            />
            {standout.chronic_bound_days != null && (
              <Fact
                label="Days bound / 30"
                value={standout.chronic_bound_days}
              />
            )}
          </div>
        </div>
      )}
      <HistoryBlock
        low={row.settled_history_p10 ?? null}
        q25={row.settled_history_p25 ?? null}
        median={row.settled_history_p50 ?? null}
        q75={row.settled_history_p75 ?? null}
        high={row.settled_history_p90 ?? null}
        mark={settled ? row.settled_total ?? null : row.forecast_total ?? null}
        values={row.settled_history ?? []}
        unit="Σμ"
      />
      <div className="bdp-reach">
        <span className="bdp-fact__label">
          Grid reach · import ↔ export{" "}
          {reach && !loading && <em>{reach.sps.length} located</em>}
        </span>
        <div className="bdp-reach__dipole">
          <Dipole imp={imp} exp={exp} />
        </div>
        {loading ? (
          <div className="cr-mem-msg">loading members…</div>
        ) : (
          <MemberList reach={reach} />
        )}
        <SfDipoleLegend />
      </div>
    </>
  );
}

function NodeEvidence({
  ranked,
  standout,
  settled,
}: {
  ranked: TopNodeRow | null;
  standout: NodeStandoutRow | null;
  settled: boolean;
}) {
  // Both node schemas share these fields; prefer whichever the selection carried.
  const zone = ranked?.zone ?? standout?.zone ?? null;
  const driver = ranked?.dominant_driver ?? standout?.dominant_driver ?? null;
  const driverShare = ranked?.driver_share ?? standout?.driver_share ?? null;
  const forecastRank = ranked?.forecast_rank ?? standout?.forecast_rank ?? null;
  const forecastTotal = ranked?.forecast_total ?? standout?.forecast_total ?? 0;
  const settledRank = ranked?.settled_rank ?? standout?.settled_rank ?? null;
  const settledTotal = ranked?.settled_total ?? standout?.settled_total ?? null;
  const essp = ranked?.essp_member_count ?? standout?.essp_member_count ?? null;
  const history = ranked ?? standout;
  return (
    <>
      <div className="bdp-grid">
        <Fact label="Zone" value={zoneLabel(zone)} />
        <Fact
          label="Dominant driver"
          value={
            <span title={driver ?? undefined}>
              {constraintName(driver)}
              {driverShare != null && (
                <small className="bdp-share"> {percent(driverShare)}</small>
              )}
            </span>
          }
        />
        <Fact label="Forecast rank" value={forecastRank ?? "—"} />
        <Fact
          label="Forecast 7×16 $/MWh"
          value={usd(forecastTotal, 2)}
          tone={dollarTone(forecastTotal)}
        />
        {ranked?.coverage != null && (
          <Fact label="SF coverage" value={percent(ranked.coverage)} />
        )}
        {essp != null && essp > 1 && (
          <Fact label="ESSP members" value={`≈${essp}`} />
        )}
        {settled && (
          <>
            <Fact
              label="DAM rank"
              value={rankMovement(forecastRank, settledRank)}
            />
            <Fact
              label="DAM 7×16 $/MWh"
              value={settledTotal == null ? "—" : usd(settledTotal, 2)}
              tone={dollarTone(settledTotal)}
            />
            {ranked?.delta != null && (
              <Fact
                label="Δ vs forecast"
                value={usd(ranked.delta, 2)}
                tone={dollarTone(ranked.delta)}
              />
            )}
          </>
        )}
      </div>
      {standout && (
        <div className="bdp-why">
          <span className="bdp-fact__label">Why it stood out</span>
          <p>{STANDOUT_NODE_KIND[standout.kind] ?? standout.kind}</p>
          <div className="bdp-grid bdp-grid--why">
            <Fact label="Today" value={usd(standout.forecast_total, 2)} />
            <Fact
              label="30-day median"
              value={usd(standout.forecast_history_median, 2)}
            />
            <Fact label="History days" value={standout.forecast_history_days} />
          </div>
        </div>
      )}
      {history && (
        <HistoryBlock
          low={history.settled_history_p10}
          q25={history.settled_history_p25}
          median={history.settled_history_p50}
          q75={history.settled_history_p75}
          high={history.settled_history_p90}
          mark={settled ? settledTotal : forecastTotal}
          values={history.settled_history}
          unit="$/MWh"
        />
      )}
    </>
  );
}

export default function BriefDetailPanel({
  selection,
  settled,
  heroCursor,
  onClose,
}: Props) {
  const panelRef = useRef<HTMLElement>(null);

  // Dialog focus contract (matches MobileDrawer): focus the close control on
  // open, trap Tab within the panel, close on Escape, and return focus to the
  // triggering row when the panel unmounts.
  useEffect(() => {
    if (!selection) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const panel = panelRef.current;
    const focusable = () =>
      panel?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      ) ?? [];
    const closeButton = panel?.querySelector<HTMLElement>("[data-panel-close]");
    requestAnimationFrame(() => closeButton?.focus());

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const targets = focusable();
      if (targets.length === 0) {
        event.preventDefault();
        return;
      }
      const first = targets[0];
      const last = targets[targets.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previouslyFocused?.focus();
    };
  }, [selection, onClose]);

  if (!selection) return null;

  const geo = selectionGeo(selection);
  const key = selectionKey(selection);
  const title = geo === "constraint" ? constraintName(key) : key;
  const eyebrow =
    selection.kind === "standout-constraint"
      ? "Standout · Constraint"
      : selection.kind === "standout-node"
      ? "Standout · Node"
      : selection.kind === "constraint"
      ? "Top constraint"
      : "Top nodal congestion";
  const mapHref = briefElementMapHref(heroCursor, selection);

  return (
    <div className="bdp" role="presentation">
      <ConstraintReachStyles />
      <button
        type="button"
        className="bdp__backdrop"
        aria-label="Close detail panel"
        onClick={onClose}
      />
      <aside
        ref={panelRef}
        className="bdp__panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby={TITLE_ID}
      >
        <div className="bdp__head">
          <div>
            <p className="bdp__eyebrow">{eyebrow}</p>
            <h2 id={TITLE_ID} className="bdp__title">
              {title}
            </h2>
            {geo === "constraint" && key.includes("|") && (
              <p className="bdp__subtitle">{key}</p>
            )}
          </div>
          <button
            type="button"
            data-panel-close
            className="bdp__close"
            aria-label="Close detail panel"
            onClick={onClose}
          >
            ✕
          </button>
        </div>

        <div className="bdp__mode">
          <span
            className={
              settled ? "bdp__chip bdp__chip--settled" : "bdp__chip"
            }
          >
            {settled ? "DAM settled" : "Forecast"}
          </span>
        </div>

        <div className="bdp__body">
          {selection.kind === "standout-constraint" ? (
            <ConstraintEvidence
              row={selection.row}
              standout={selection.row}
              settled={settled}
            />
          ) : selection.kind === "constraint" ? (
            <ConstraintEvidence
              row={selection.row}
              standout={null}
              settled={settled}
            />
          ) : selection.kind === "standout-node" ? (
            <NodeEvidence ranked={null} standout={selection.row} settled={settled} />
          ) : (
            <NodeEvidence ranked={selection.row} standout={null} settled={settled} />
          )}
        </div>

        <div className="bdp__foot">
          <Link className="bdp__map" to={mapHref}>
            Open in Map →
          </Link>
          <p className="bdp__foot-note">
            Opens the full interactive Map with this{" "}
            {geo === "constraint" ? "constraint" : "node"} selected on the
            Forecast × Congestion view.
          </p>
        </div>
      </aside>

      <style>{`
        .bdp { position: fixed; inset: 0; z-index: 90; display: flex; justify-content: flex-end; }
        .bdp__backdrop { position: absolute; inset: 0; border: 0; border-radius: 0; padding: 0; background: rgba(0,0,0,0.5); cursor: pointer; }
        .bdp__panel {
          position: relative;
          width: min(94vw, 440px);
          height: 100%;
          display: flex;
          flex-direction: column;
          background: var(--bg-panel);
          border-left: 1px solid var(--border-bright);
          box-shadow: var(--shadow-panel, 0 8px 30px rgb(0 0 0 / 32%));
          font-variant-numeric: tabular-nums;
        }
        .bdp__head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 18px 18px 12px; border-bottom: 1px solid var(--border); }
        .bdp__eyebrow { margin: 0 0 6px; color: var(--text-secondary); font: var(--fw-label) var(--fs-xs) var(--font-label); letter-spacing: var(--track-label); text-transform: uppercase; }
        .bdp__title { margin: 0; font-family: var(--font-mono); font-size: var(--fs-xl); line-height: 1.2; overflow-wrap: anywhere; }
        .bdp__subtitle { margin: 4px 0 0; color: var(--text-muted); font-family: var(--font-mono); font-size: var(--fs-micro); overflow-wrap: anywhere; }
        .bdp__close { width: 34px; height: 34px; flex: 0 0 auto; padding: 0; border: 1px solid var(--border); border-radius: 3px; background: var(--bg-base); color: var(--text-primary); font-size: 15px; cursor: pointer; }
        .bdp__close:hover { border-color: var(--accent); color: var(--accent); }
        .bdp__close:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
        .bdp__mode { padding: 12px 18px 0; }
        .bdp__chip { display: inline-block; padding: 3px 8px; border: 1px solid color-mix(in srgb, var(--accent) 45%, var(--border)); border-radius: 3px; background: var(--accent-dim); color: var(--accent); font: var(--fw-label) var(--fs-micro) var(--font-label); letter-spacing: var(--track-label); text-transform: uppercase; }
        .bdp__chip--settled { border-color: color-mix(in srgb, var(--ok) 55%, var(--border)); background: color-mix(in srgb, var(--ok) 12%, transparent); color: var(--ok); }
        .bdp__body { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 14px 18px 18px; }
        .bdp-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; margin-top: 8px; border: 1px solid var(--border); background: var(--border); }
        .bdp-fact { min-width: 0; padding: 9px 10px; background: var(--bg-panel); }
        .bdp-fact__label { display: block; color: var(--text-muted); font-size: var(--fs-label); line-height: 1.3; overflow-wrap: anywhere; }
        .bdp-fact__value { display: block; margin-top: 3px; color: var(--text-primary); font-family: var(--font-mono); font-size: var(--fs-md); overflow-wrap: anywhere; }
        .bdp-fact__value--pos { color: var(--danger, #d94444); }
        .bdp-fact__value--neg { color: var(--accent); }
        .bdp-share { color: var(--text-muted); font-family: var(--font-sans); font-size: var(--fs-micro); }
        .bdp-why { margin-top: 16px; padding: 12px; border: 1px solid var(--border); background: color-mix(in srgb, var(--warn) 5%, transparent); }
        .bdp-why p { margin: 4px 0 0; color: var(--text-secondary); font-size: var(--fs-label); line-height: 1.4; }
        .bdp-grid--why { grid-template-columns: repeat(2, minmax(0, 1fr)); border-color: var(--border); }
        .bdp-history { margin-top: 16px; }
        .bdp-reach { margin-top: 16px; }
        .bdp-reach .bdp-fact__label em { font-style: normal; color: var(--text-muted); }
        .bdp-reach__dipole { width: 160px; margin: 8px 0 10px; }
        .bdp-history__glyphs { display: flex; align-items: center; gap: 16px; margin-top: 8px; }
        .bdp__foot { padding: 14px 18px 18px; border-top: 1px solid var(--border); }
        .bdp__map { display: inline-block; padding: 8px 14px; border: 1px solid color-mix(in srgb, var(--accent) 45%, var(--border)); border-radius: 4px; background: var(--accent-dim); color: var(--accent); font: 700 var(--fs-md) var(--font-label); letter-spacing: var(--track-label); text-decoration: none; }
        .bdp__map:hover { background: color-mix(in srgb, var(--accent-dim) 65%, var(--accent) 14%); border-color: var(--accent); }
        .bdp__foot-note { margin: 8px 0 0; color: var(--text-muted); font-size: var(--fs-micro); line-height: 1.4; }
      `}</style>
    </div>
  );
}
