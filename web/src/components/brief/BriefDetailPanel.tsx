import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
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
  compactMoney,
  constraintName,
  percent,
  rankMovement,
  usd,
  zoneLabel,
} from "../../lib/format";
import { HistoryWhisker } from "./HistoryGlyphs";
import {
  ConstraintReachStyles,
  Dipole,
  MemberList,
  SfDipoleLegend,
  dipoleCounts,
  REACH_K,
  useConstraintReach,
} from "../panels/ConstraintReach";
import MiniMap from "../map/MiniMap";

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

// One label→value row of the evidence table (rendered as a two-column
// definition list; each Fact is a dt/dd pair). `tone` colors node dollars by
// sign the way the tables do; a missing value renders an em dash, never a 0.
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
    <div className="bdp-kv__row">
      <span className="bdp-kv__label">{label}</span>
      <span
        className={
          tone === "positive"
            ? "bdp-kv__value bdp-kv__value--pos"
            : tone === "negative"
            ? "bdp-kv__value bdp-kv__value--neg"
            : "bdp-kv__value"
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
// The panel has room, so both glyphs are full-width and carry real numbers: the
// whisker prints p10 / today / p90 under their marks, the bars a left y-axis.
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
  // Today's mark is what drives the whisker; the p10–p90 band is optional (an
  // element with no settled history still shows today). The label math mirrors
  // HistoryWhisker so each label sits over its true point.
  const hasBand = low != null && high != null;
  const scale =
    mark != null
      ? (() => {
          const min = Math.min(hasBand ? low : mark, mark, 0);
          const max = Math.max(hasBand ? high : mark, mark, 0);
          const span = Math.max(max - min, 1);
          const pos = (v: number) =>
            Math.min(100, Math.max(0, ((v - min) / span) * 100));
          return {
            p10: hasBand ? pos(low) : null,
            p90: hasBand ? pos(high) : null,
            mark: pos(mark),
          };
        })()
      : null;
  // Near the ends, shift the label to the point's inner side instead of moving
  // the anchor: keeps it over the point without clipping the panel edge.
  const tickShift = (p: number) => (p <= 6 ? "0" : p >= 94 ? "-100%" : "-50%");
  return (
    <div className="bdp-history">
      <span className="bdp-section-title">30-day history</span>
      <div className="bdp-history__row">
        <span className="bdp-history__cap">{unit} vs its own 30 days</span>
        <div className="bdp-whisker">
          {/* p10 / p90 sit ABOVE the number line, today BELOW it, so a value
              landing near p90 no longer prints on top of it. p10/p90 appear only
              when the element has a settled band. */}
          {scale && scale.p10 != null && scale.p90 != null && (
            <div className="bdp-whisker__top">
              <span
                className="bdp-whisker__tick"
                style={{ left: `${scale.p10}%`, transform: `translateX(${tickShift(scale.p10)})` }}
              >
                <em>p10</em>
                {compactMoney(low!)}
              </span>
              <span
                className="bdp-whisker__tick"
                style={{ left: `${scale.p90}%`, transform: `translateX(${tickShift(scale.p90)})` }}
              >
                <em>p90</em>
                {compactMoney(high!)}
              </span>
            </div>
          )}
          <HistoryWhisker
            low={low}
            q25={q25}
            median={median}
            q75={q75}
            high={high}
            mark={mark}
          />
          {scale && (
            <div className="bdp-whisker__bottom">
              <span
                className="bdp-whisker__tick bdp-whisker__tick--mark"
                style={{ left: `${scale.mark}%`, transform: `translateX(${tickShift(scale.mark)})` }}
              >
                {compactMoney(mark!)}
                <em>today</em>
              </span>
            </div>
          )}
        </div>
      </div>
      <div className="bdp-history__row">
        <span className="bdp-history__cap">
          {unit} each of the last 30 days, then today
          {!values.length && (
            <em className="bdp-history__none"> — no prior settled days</em>
          )}
        </span>
        <SignedBars values={values} today={mark} fmt={compactMoney} />
      </div>
    </div>
  );
}

// A diverging bar chart for the trailing daily series: each bar grows up
// (positive / export) or down (negative / import) from a zero baseline, so an
// import node's negative days render as real bars instead of collapsing to the
// floor. Today's value is appended as a highlighted final bar; the y-axis shows
// the true min/max and marks zero when the range crosses it.
function SignedBars({
  values,
  today,
  fmt,
}: {
  values: number[];
  today: number | null;
  fmt: (n: number) => string;
}) {
  const series = [
    ...values.map((v) => ({ v, today: false })),
    ...(today != null ? [{ v: today, today: true }] : []),
  ];
  if (!series.length) return <span className="an-table__missing">—</span>;
  const nums = series.map((s) => s.v);
  const maxV = Math.max(...nums, 0);
  const minV = Math.min(...nums, 0);
  const range = maxV - minV || 1;
  const zeroPct = (maxV / range) * 100; // % from the top where 0 sits
  const crossesZero = minV < 0 && maxV > 0;
  return (
    <div className="bdp-sbars">
      <div className="bdp-sbars__axis" aria-hidden="true">
        <span className="bdp-sbars__ax bdp-sbars__ax--top">{fmt(maxV)}</span>
        {crossesZero && (
          <span
            className="bdp-sbars__ax bdp-sbars__ax--zero"
            style={{ top: `${zeroPct}%` }}
          >
            0
          </span>
        )}
        <span className="bdp-sbars__ax bdp-sbars__ax--bot">{fmt(minV)}</span>
      </div>
      <div
        className="bdp-sbars__plot"
        style={{ ["--zero" as string]: `${zeroPct}%` }}
      >
        <span className="bdp-sbars__zline" />
        {series.map((s, i) => {
          const barStyle: CSSProperties =
            s.v >= 0
              ? {
                  bottom: "calc(100% - var(--zero))",
                  height: `${Math.max(1.5, (s.v / range) * 100)}%`,
                }
              : {
                  top: "var(--zero)",
                  height: `${Math.max(1.5, (-s.v / range) * 100)}%`,
                };
          if (s.today)
            barStyle.background =
              s.v >= 0 ? "var(--danger, #d94444)" : "var(--accent)";
          return (
            <span key={i} className="bdp-sbars__col">
              <span
                className={
                  s.today ? "bdp-sbars__bar bdp-sbars__bar--today" : "bdp-sbars__bar"
                }
                style={barStyle}
              />
            </span>
          );
        })}
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
  t,
}: {
  // Both constraint schemas carry every field this reads; they differ only in
  // nullability, so the union widens the numeric cells to `number | null` — which
  // the em-dash guards below already handle.
  row: StandoutRow | TopConstraintRow;
  settled: boolean;
  standout: StandoutRow | null;
  // The Brief cursor's instant — selects the delivery day the reach describes.
  t?: Date;
}) {
  // The constraint's SF reach — the located member nodes it drives and the
  // import↔export dipole they form — is the same evidence the map's Constraints
  // sidebar shows; both read it through the shared reach hook/cache.
  const { reach, loading } = useConstraintReach(row.constraint_key, REACH_K, t);
  const { imp, exp } = dipoleCounts(reach);
  return (
    <>
      <div className="bdp-kv">
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
          <span className="bdp-section-title">Why it stood out</span>
          <p>{STANDOUT_CONSTRAINT_KIND[standout.kind] ?? standout.kind}</p>
          <div className="bdp-kv">
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
        <span className="bdp-section-title">
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
      <div className="bdp-kv">
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
          <span className="bdp-section-title">Why it stood out</span>
          <p>{STANDOUT_NODE_KIND[standout.kind] ?? standout.kind}</p>
          <div className="bdp-kv">
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
  const open = selection != null;

  // The drawer + scrim stay mounted permanently and slide via a class toggle,
  // never a mount-time animation (that races React's first paint and flashes the
  // panel's final frame — the FOUT). `rendered` retains the last selection so the
  // panel keeps its content while it slides OUT, after `selection` has gone null.
  // Derived during render (not in an effect) so the first open paints its content
  // and closed transform in the same frame — no empty first frame.
  const [rendered, setRendered] = useState<BriefSelection | null>(null);
  if (selection && selection !== rendered) setRendered(selection);

  // Dialog focus contract (matches MobileDrawer): focus the close control on
  // open, trap Tab within the panel, close on Escape, and return focus to the
  // triggering row on close.
  useEffect(() => {
    if (!open) return;
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
    // Lock the page scroll behind the modal so the dimmed Brief can't scroll
    // under it; restore the prior value on close.
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus();
    };
  }, [selection, onClose]);

  const geo = rendered ? selectionGeo(rendered) : "constraint";
  const key = rendered ? selectionKey(rendered) : "";
  const title = geo === "constraint" ? constraintName(key) : key;
  // The contingency is the second half of a constraint key; shown after the name
  // in lighter grey (no "|"). Nodes have none.
  const contingency =
    geo === "constraint" && key.includes("|") ? key.split("|")[1] : "";
  const eyebrow = !rendered
    ? ""
    : rendered.kind === "standout-constraint"
    ? "Standout · Constraint"
    : rendered.kind === "standout-node"
    ? "Standout · Node"
    : rendered.kind === "constraint"
    ? "Top constraint"
    : "Top nodal congestion";
  const mapHref = rendered ? briefElementMapHref(heroCursor, rendered) : "#";
  // The Brief cursor as an instant: reach and footprint are served for its CT
  // delivery day (0144), so the panel's evidence describes the day the Brief is
  // showing rather than whatever day was built last.
  const heroCursorT = heroCursor?.t;
  const cursorTs = useMemo(
    () => (heroCursorT ? new Date(heroCursorT) : undefined),
    [heroCursorT]
  );

  // Portal to <body> and keep the scrim + panel permanently mounted (see the
  // `rendered` note above). Both are `position: fixed` siblings — NOT nested in a
  // full-viewport wrapper — so when closed (scrim visibility:hidden, panel slid
  // off-screen) nothing intercepts clicks on the page beneath. The `--on` class
  // drives a CSS *transition* from the pre-existing closed state, so the slide is
  // smooth in and out with no mount-time flash.
  return createPortal(
    <>
      <ConstraintReachStyles />
      <div
        className={`bdp__scrim${open ? " bdp__scrim--on" : ""}`}
        aria-hidden="true"
        onClick={onClose}
      />
      <aside
        ref={panelRef}
        className={`bdp__panel${open ? " bdp__panel--on" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={TITLE_ID}
        aria-hidden={!open}
      >
        {rendered && (
          <>
            <div className="bdp__head">
              <div className="bdp__head-main">
                <p className="bdp__eyebrow">{eyebrow}</p>
                <h2 id={TITLE_ID} className="bdp__title">
                  {title}
                  {contingency && (
                    <span className="bdp__contingency"> {contingency}</span>
                  )}
                </h2>
                {/* Basis: "DAM settled" once settled, else "Forecast" — which is
                    also what a t+2 preview horizon shows (basis stays forecast
                    until DAM clears). Sits in the name's left column. */}
                <span
                  className={
                    settled ? "bdp__chip bdp__chip--settled" : "bdp__chip"
                  }
                >
                  {settled ? "DAM settled" : "Forecast"}
                </span>
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

            <div className="bdp__body">
              <MiniMap mode={geo} selectionKey={key} mapHref={mapHref} t={cursorTs} />
              {rendered.kind === "standout-constraint" ? (
                <ConstraintEvidence
                  row={rendered.row}
                  standout={rendered.row}
                  settled={settled}
                  t={cursorTs}
                />
              ) : rendered.kind === "constraint" ? (
                <ConstraintEvidence
                  row={rendered.row}
                  standout={null}
                  settled={settled}
                  t={cursorTs}
                />
              ) : rendered.kind === "standout-node" ? (
                <NodeEvidence ranked={null} standout={rendered.row} settled={settled} />
              ) : (
                <NodeEvidence ranked={rendered.row} standout={null} settled={settled} />
              )}
            </div>
          </>
        )}
      </aside>

      <style>{`
        .bdp__scrim {
          position: fixed; inset: 0; z-index: 89;
          background: rgba(0,0,0,0.5);
          opacity: 0; visibility: hidden; cursor: pointer;
          transition: opacity 180ms ease, visibility 0s linear 180ms;
        }
        .bdp__scrim--on { opacity: 1; visibility: visible; transition: opacity 180ms ease, visibility 0s; }
        .bdp__panel {
          position: fixed; top: 0; right: 0; bottom: 0; z-index: 90;
          width: min(94vw, 440px);
          display: flex;
          flex-direction: column;
          background: var(--bg-panel);
          border-left: 1px solid var(--border-bright);
          box-shadow: var(--shadow-panel, 0 8px 30px rgb(0 0 0 / 32%));
          font-variant-numeric: tabular-nums;
          transform: translateX(100%);
          visibility: hidden;
          transition: transform 200ms cubic-bezier(0.22, 0.61, 0.36, 1), visibility 0s linear 200ms;
        }
        .bdp__panel--on { transform: none; visibility: visible; transition: transform 200ms cubic-bezier(0.22, 0.61, 0.36, 1), visibility 0s; }
        @media (prefers-reduced-motion: reduce) {
          .bdp__scrim, .bdp__panel { transition: none; }
        }
        .bdp__head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 18px 18px 14px; border-bottom: 1px solid var(--border); }
        .bdp__head-main { min-width: 0; }
        .bdp__eyebrow { margin: 0 0 6px; color: var(--text-secondary); font: var(--fw-label) var(--fs-xs) var(--font-label); letter-spacing: var(--track-label); text-transform: uppercase; }
        .bdp__title { margin: 0; font-family: var(--font-mono); font-size: var(--fs-xl); line-height: 1.2; overflow-wrap: anywhere; }
        .bdp__contingency { color: var(--text-muted); font-weight: 400; }
        .bdp__close { width: 34px; height: 34px; flex: 0 0 auto; padding: 0; border: 1px solid var(--border); border-radius: 3px; background: var(--bg-base); color: var(--text-primary); font-size: 15px; cursor: pointer; }
        .bdp__close:hover { border-color: var(--accent); color: var(--accent); }
        .bdp__close:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
        .bdp__chip { display: inline-block; margin-top: 10px; padding: 3px 8px; border: 1px solid color-mix(in srgb, var(--accent) 45%, var(--border)); border-radius: 3px; background: var(--accent-dim); color: var(--accent); font: var(--fw-label) var(--fs-micro) var(--font-label); letter-spacing: var(--track-label); text-transform: uppercase; white-space: nowrap; }
        .bdp__chip--settled { border-color: color-mix(in srgb, var(--ok) 55%, var(--border)); background: color-mix(in srgb, var(--ok) 12%, transparent); color: var(--ok); }
        .bdp__body { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 14px 18px 18px; }
        /* A section heading inside the panel — title-sized (bigger than the kv
           labels) so history / reach / why read as their own blocks. */
        .bdp-section-title { display: block; margin-bottom: 8px; color: var(--text-secondary); font: var(--fw-label) var(--fs-md) var(--font-label); letter-spacing: var(--track-label); text-transform: uppercase; }
        .bdp-section-title em { font-style: normal; color: var(--text-muted); text-transform: none; }
        /* Evidence as a minimal, headerless label→value list: label in a fixed
           column, value left-aligned right after it (not pushed to the edge). */
        .bdp-kv { display: flex; flex-direction: column; margin: 0; }
        .bdp-kv__row { display: flex; gap: 14px; align-items: baseline; padding: 5px 0; border-bottom: 1px solid color-mix(in srgb, var(--border) 60%, transparent); }
        .bdp-kv__row:last-child { border-bottom: 0; }
        .bdp-kv__label { flex: 0 0 118px; color: var(--text-muted); font-size: var(--fs-label); }
        .bdp-kv__value { flex: 1 1 auto; min-width: 0; color: var(--text-primary); font-family: var(--font-mono); font-size: var(--fs-md); text-align: left; overflow-wrap: anywhere; }
        .bdp-kv__value--pos { color: var(--danger, #d94444); }
        .bdp-kv__value--neg { color: var(--accent); }
        .bdp-share { color: var(--text-muted); font-family: var(--font-sans); font-size: var(--fs-micro); }
        .bdp-why { margin-top: 18px; padding: 12px; border: 1px solid var(--border); background: color-mix(in srgb, var(--warn) 5%, transparent); }
        .bdp-why p { margin: 0 0 4px; color: var(--text-secondary); font-size: var(--fs-label); line-height: 1.4; }
        /* A separator + space above the history block (below the kv table). */
        .bdp-history { margin-top: 22px; padding-top: 22px; border-top: 1px solid var(--border); }
        .bdp-history__row { margin-top: 22px; }
        .bdp-history__cap { display: block; margin-bottom: 12px; color: var(--text-secondary); font-size: var(--fs-body); }
        .bdp-history__none { font-style: normal; color: var(--text-muted); }
        /* Each glyph gets its own full-width line. */
        .bdp-history .an-history-whisker { display: block; width: 100%; height: 20px; }
        /* Whisker value scale: p10 / p90 ABOVE the number line, today BELOW. */
        .bdp-whisker { position: relative; }
        .bdp-whisker__top { position: relative; height: 26px; margin-bottom: 4px; }
        .bdp-whisker__bottom { position: relative; height: 26px; margin-top: 4px; }
        .bdp-whisker__tick { position: absolute; transform: translateX(-50%); display: flex; flex-direction: column; align-items: center; line-height: 1.15; color: var(--text-secondary); font-family: var(--font-mono); font-size: var(--fs-micro); white-space: nowrap; }
        .bdp-whisker__top .bdp-whisker__tick { bottom: 0; }
        .bdp-whisker__bottom .bdp-whisker__tick { top: 0; }
        .bdp-whisker__tick em { font-style: normal; color: var(--text-muted); font-family: var(--font-sans); font-size: 9px; letter-spacing: .02em; text-transform: uppercase; }
        .bdp-whisker__tick--mark { color: var(--danger, #d94444); font-weight: 700; }
        /* Signed daily bars — up (positive/export) / down (negative/import) from
           a zero baseline, with a left y-axis and today highlighted. */
        .bdp-sbars { display: flex; align-items: stretch; gap: 8px; }
        .bdp-sbars__axis { position: relative; width: 42px; height: 56px; flex: 0 0 auto; border-right: 1px solid var(--border); color: var(--text-muted); font-family: var(--font-mono); font-size: 9px; }
        .bdp-sbars__ax { position: absolute; right: 6px; white-space: nowrap; }
        .bdp-sbars__ax--top { top: 0; }
        .bdp-sbars__ax--bot { bottom: 0; }
        .bdp-sbars__ax--zero { transform: translateY(-50%); }
        .bdp-sbars__plot { position: relative; flex: 1 1 auto; min-width: 0; height: 56px; display: flex; align-items: stretch; gap: 1px; }
        .bdp-sbars__zline { position: absolute; left: 0; right: 0; top: var(--zero); height: 1px; background: var(--border-bright); }
        .bdp-sbars__col { position: relative; flex: 1 1 0; min-width: 0; }
        .bdp-sbars__bar { position: absolute; left: 0; right: 0; min-height: 1px; border-radius: 1px; background: color-mix(in srgb, var(--accent) 55%, var(--border)); }
        .bdp-sbars__bar--today { z-index: 1; box-shadow: 0 0 0 1px var(--bg-panel); }
        /* A subtle divider before the reach block, to separate it from history. */
        .bdp-reach { margin-top: 22px; padding-top: 22px; border-top: 1px solid var(--border); }
        .bdp-reach__dipole { width: 100%; margin: 8px 0 10px; }
        /* Legend: one colour per line, no larger than the section titles. */
        .bdp-reach .cr-legend { flex-direction: column; gap: 4px; margin-top: 10px; }
        .bdp-reach .cr-legend-item { font-size: var(--fs-label); }
      `}</style>
    </>,
    document.body
  );
}
