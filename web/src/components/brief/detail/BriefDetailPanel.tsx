import { useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useModalDismiss } from "../../../hooks/useModalDismiss";
import {
  briefElementMapHref,
  selectionGeo,
  selectionKey,
  type BriefSelection,
} from "../../../lib/briefSelection";
import { constraintName } from "../../../lib/format";
import { ConstraintReachStyles } from "../../panels/ConstraintReach";
import MiniMap from "../../map/MiniMap";
import { ConstraintEvidence } from "./ConstraintEvidence";
import { NodeEvidence } from "./NodeEvidence";
import "../../../features/brief/brief.css";

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
  // open, trap Tab within the panel, close on Escape, return focus to the
  // triggering row on close, and lock the dimmed Brief from scrolling underneath.
  useModalDismiss({
    open,
    onClose,
    panelRef,
    initialFocus: "[data-panel-close]",
    trapFocus: true,
    lockScroll: true,
  });

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
        /* Evidence as a minimal, headerless label→value list: fixed label
           column, value left-aligned right after it (not pushed to the edge).
           The row is the shared components/detail/Fact; only the drawer's
           label/value widths differ from the base flex layout. */
        .bdp-kv { display: flex; flex-direction: column; margin: 0; }
        .bdp-kv .kv__label { flex: 0 0 118px; }
        .bdp-kv .kv__value { flex: 1 1 auto; }
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
