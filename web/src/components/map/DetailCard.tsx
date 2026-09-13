import { useState } from "react";
import type { ExposuresResponse, ConstraintReach } from "../../api/types";
import {
  ExposuresBody,
  NodeChip,
  ReachBody,
  SpBody,
  TypeChip,
  type HoveredSp,
} from "./detail";

interface Props {
  hoveredSp?: HoveredSp | null;
  pinnedSp?: HoveredSp | null;
  // Top-k constraints driving the pinned SP (the node-explorer click). Loading
  // while null with a pinned SP; the card renders the SP body meanwhile.
  exposures?: ExposuresResponse | null;
  exposuresLoading?: boolean;
  // The scrubber's instant. The contribution list is specific to this hour, so
  // the basis header names it rather than saying "this hour" and leaving the
  // reader to assume it followed the cursor.
  cursorTs?: Date;
  // Constraint-reach mode (the constraint click). Wins over the SP view.
  reach?: ConstraintReach | null;
  onClose?: () => void;
  onCloseReach?: () => void;
  // Click a driver row → trace that constraint's reach.
  onSelectConstraint?: (constraintKey: string) => void;
  // Hover a driver row → isolate that constraint on the map (null on leave).
  onHoverConstraint?: (constraintKey: string | null) => void;
  // Hover a reach member node → ring it on the map (null on leave).
  onHoverMember?: (sp: string | null) => void;
  // Click a reach member node → load that node's card (leaves reach mode).
  onSelectMember?: (sp: string) => void;
  // Whether to render the pinned SP's SF-driver section. The actual/ERCOT pane
  // passes false — its card is scoped to realized values only (drivers are a
  // prediction-side concern). Defaults to true.
  showDrivers?: boolean;
  // Constraint reach values follow the pane: forecast artifact values on the
  // prediction pane, published DAM values on the ERCOT pane.
  reachValueMode?: "forecast" | "ercot";
  // Which side of the decomposition this card represents. Compare mounts one
  // card per pane, so this is passed explicitly rather than inferred from the
  // URL's layout state.
  valueMode: "forecast" | "ercot";
  mobile?: boolean;
}

export default function DetailCard({
  hoveredSp,
  pinnedSp,
  exposures,
  exposuresLoading,
  cursorTs,
  reach,
  onClose,
  onCloseReach,
  onSelectConstraint,
  onHoverConstraint,
  onHoverMember,
  onSelectMember,
  showDrivers = true,
  reachValueMode = "forecast",
  valueMode,
  mobile = false,
}: Props) {
  // Reach (constraint pinned) wins; otherwise pinned SP wins over hover.
  const inReach = !!reach;
  const sp = mobile ? pinnedSp : pinnedSp ?? hoveredSp;
  const isPinned = !!pinnedSp;
  // No SF for this node on this day (0146). Guarded on `sp`, so a stale
  // response never labels the next node.
  const noSf =
    !inReach && isPinned && exposures?.sp === sp?.spId
      ? exposures?.unavailable_reason
      : null;
  const noSfLabel =
    noSf === "sp_not_in_service"
      ? "Non-existent"
      : noSf === "sp_not_in_fit"
      ? "Not in fit"
      : null;
  const [expanded, setExpanded] = useState(false);

  if (!inReach && !sp) return null;

  return (
    <div
      className={`detail-card ${
        inReach || isPinned ? "detail-card--pinned" : ""
      }${mobile ? " detail-card--mobile" : ""}${
        expanded ? " detail-card--expanded" : ""
      }`}
    >
      <div className="detail-card__header">
        <div className="detail-card__title">
          {inReach ? (
            <>
              <TypeChip ctype={reach!.ctype} />
              <span className="detail-card__id mono">
                {reach!.constraint_key}
              </span>
            </>
          ) : (
            <>
              <NodeChip />
              <span className="detail-card__id mono">{sp!.spId}</span>
            </>
          )}
        </div>
        {noSfLabel && (
          <span className="detail-card__badge label">{noSfLabel}</span>
        )}
        {mobile && (
          <button
            className="detail-card__expand"
            onClick={() => setExpanded((value) => !value)}
            aria-expanded={expanded}
            aria-label={expanded ? "Collapse details" : "Expand details"}
          >
            {expanded ? "⌄" : "⌃"}
          </button>
        )}
        {inReach && onCloseReach ? (
          <button
            className="detail-card__close"
            onClick={onCloseReach}
            aria-label="Close"
          >
            ×
          </button>
        ) : (
          isPinned &&
          onClose && (
            <button
              className="detail-card__close"
              onClick={onClose}
              aria-label="Close"
            >
              ×
            </button>
          )
        )}
      </div>

      <div className="detail-card__body">
        {inReach ? (
          <ReachBody
            reach={reach!}
            onHoverMember={onHoverMember}
            onSelectMember={onSelectMember}
            valueMode={reachValueMode}
          />
        ) : (
          <>
            <SpBody sp={sp!} valueMode={valueMode} />
            {isPinned && showDrivers && !noSfLabel && (
              <div className="detail-card__section">
                <ExposuresBody
                  exposures={exposures ?? null}
                  loading={exposuresLoading}
                  cursorTs={cursorTs}
                  onSelectConstraint={onSelectConstraint}
                  onHoverConstraint={onHoverConstraint}
                />
              </div>
            )}
          </>
        )}
      </div>

      <style>{`
        .detail-card {
          position: absolute;
          top: 12px;
          left: 12px;
          width: 340px;
          background: var(--bg-glass);
          border: 1px solid var(--border-bright);
          border-radius: 4px;
          padding: 0;
          backdrop-filter: blur(6px);
          z-index: 10;
          box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
          font-size: 13px;
        }
        .detail-card--pinned {
          border-color: var(--accent);
          box-shadow: 0 4px 20px rgba(56, 189, 248, 0.2);
        }

        .detail-card__header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 8px 10px;
          border-bottom: 1px solid var(--border);
        }
        .detail-card__title {
          display: flex;
          align-items: baseline;
          gap: 8px;
          min-width: 0;
        }
        .detail-card__badge {
          margin-left: auto;
          margin-right: 8px;
          border: 1px solid color-mix(in srgb, var(--warn) 45%, var(--border));
          border-radius: 3px;
          padding: 1px 5px;
          background: color-mix(in srgb, var(--warn) 12%, transparent);
          color: var(--warn);
          /* Uppercase, so it reads as a state stamp rather than a value; caps
             need the air, hence --track-title (index.css). */
          text-transform: uppercase;
          letter-spacing: var(--track-title);
          white-space: nowrap;
        }
        .detail-card__kind {
          color: ${"var(--accent)"};
          font-size: 10px;
        }
        .detail-card__kind--constraint { color: #c4b5fd; }
        .detail-card__id {
          font-size: 13px;
          color: var(--text-primary);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .detail-card__close {
          padding: 0;
          width: 20px;
          height: 20px;
          font-size: 18px;
          line-height: 1;
          background: transparent;
          border: 1px solid var(--border-bright);
          border-radius: 3px;
          color: var(--text-secondary);
          flex-shrink: 0;
        }
        .detail-card__close:hover {
          background: var(--danger);
          border-color: var(--danger);
          color: white;
        }
        .detail-card__expand { display: none; }

        .detail-card__body {
          padding: 6px 10px 8px;
        }
        .detail-card__section {
          margin-top: 6px;
          padding-top: 6px;
          border-top: 1px solid var(--border);
        }
        .dc-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 3px 0;
        }
        .dc-row--deemphasis { opacity: 0.56; }
        .dc-val {
          font-size: 12px;
          color: var(--text-primary);
        }
        .dc-support {
          font-size: 10px;
          color: var(--text-secondary);
          margin: -2px 0 4px;
        }
        .dc-drivers-empty {
          font-size: 11px;
          color: var(--text-muted);
          padding: 2px 0;
        }
        /* Which basis the list is ranked on — stated, not inferred (0145). */
        .dc-drivers-head {
          display: flex;
          align-items: baseline;
          justify-content: space-between;
          gap: 8px;
          padding-bottom: 3px;
        }
        .dc-drivers-basis {
          font-size: 11px;
          color: var(--text-secondary);
        }
        .dc-drivers-note {
          font-size: 10px;
          color: var(--text-secondary);
          padding-top: 4px;
        }
        .dc-driver-clip {
          color: var(--text-secondary);
          padding-left: 2px;
        }
        .dc-drivers {
          display: flex;
          flex-direction: column;
          max-height: 220px;
          overflow-y: auto;
        }
        .dc-drivers--reach {
          margin-top: 6px;
          border-top: 1px solid var(--border);
        }
        /* One grid for the header row and every driver row, so the columns line
           up. Three columns: type chip, key, contribution.
           The numeric track is a fixed width, not auto: each row is its own
           grid container, so auto sizes every row to its own content and the
           header drifts out of line with the values under it. Reach rows add a
           fourth column below. */
        .dc-driver {
          display: grid;
          grid-template-columns: 10px 1fr 58px;
          align-items: center;
          gap: 8px;
          padding: 3px 0;
          background: transparent;
          border: none;
          border-radius: 3px;
          text-align: left;
          width: 100%;
          cursor: pointer;
        }
        .dc-driver:hover { background: var(--bg-hover); }
        /* Reach rows add their signed −SF × shadow contribution at the right. */
        .dc-driver--reach-row {
          grid-template-columns: 10px 1fr 58px 58px;
        }
        .dc-driver--head {
          cursor: default;
          position: sticky;
          top: 0;
          z-index: 1;
          /* Plain white (dark: near-black) — the sticky header must be opaque so
             rows scroll under it, but --bg-panel read as a grey band against the
             card in both themes. */
          background: var(--bg-base);
          padding-bottom: 6px;
          border-bottom: 1px solid var(--border);
          margin-bottom: 6px;
        }
        .dc-driver--head:hover { background: transparent; }
        .dc-driver-col {
          font-size: 10px;
          color: var(--text-secondary);
        }
        .dc-driver-col:not(:nth-child(2)) { text-align: right; }
        .dc-chip {
          width: 9px;
          height: 9px;
          border-radius: 2px;
          flex-shrink: 0;
        }
        .dc-driver-key {
          font-size: 12px;
          color: var(--text-primary);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .dc-driver-sf {
          font-size: 12px;
          text-align: right;
        }
        .dc-driver-sup {
          font-size: 12px;
          color: var(--text-secondary);
          text-align: right;
        }
        .detail-card--mobile {
          top: auto;
          left: 0;
          bottom: 0;
          width: 100%;
          max-height: 46%;
          display: flex;
          flex-direction: column;
          border-radius: 14px 14px 0 0;
          border-bottom: 0;
          background: var(--bg-panel);
          backdrop-filter: none;
        }
        /* The mobile card's own surface is --bg-panel, so the sticky header
           matches that instead of white — same rule, no band either way. */
        .detail-card--mobile .dc-driver--head { background: var(--bg-panel); }
        .detail-card--mobile.detail-card--expanded { max-height: 86%; }
        .detail-card--mobile .detail-card__header {
          min-height: 46px;
          padding: 8px 14px;
        }
        .detail-card--mobile .detail-card__body {
          overflow-y: auto;
          overscroll-behavior: contain;
          padding: 8px 14px max(12px, env(safe-area-inset-bottom));
        }
        .detail-card--mobile .detail-card__expand {
          display: inline-flex;
          width: 28px;
          height: 28px;
          align-items: center;
          justify-content: center;
          margin-left: auto;
          margin-right: 6px;
          padding: 0;
          border: 0;
          background: transparent;
          color: var(--text-secondary);
          font-size: 18px;
        }
        .detail-card--mobile .detail-card__close {
          width: 28px;
          height: 28px;
        }
      `}</style>
    </div>
  );
}
