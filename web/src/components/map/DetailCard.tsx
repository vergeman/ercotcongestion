import { useState } from "react";
import type {
  ExposureRank,
  ExposuresResponse,
  ConstraintReach,
} from "../../api/types";
import { formatCT } from "../../lib/time";
import { shiftFactorColor } from "../../lib/colors";

interface HoveredSp {
  spId: string;
  props: Record<string, unknown>;
  // The full decomposition for the clicked SP, carried in every view so the
  // forecast error never hides raw magnitude: forecast (P50) / realized
  // congestion, their difference (error = forecast − realized), and the
  // realized side's raw DAM SPP.
  spState: {
    predicted: number | null;
    market: number | null;
    error: number | null;
    marketSpp: number | null;
    predictedSpp: number | null;
  } | null;
}

interface Props {
  hoveredSp?: HoveredSp | null;
  pinnedSp?: HoveredSp | null;
  // Top-k constraints driving the pinned SP (the node-explorer click). Loading
  // while null with a pinned SP; the card renders the SP body meanwhile.
  exposures?: ExposuresResponse | null;
  exposuresLoading?: boolean;
  // Which basis the driver list is ordered on, and the toggle that switches it
  // (0145). Owned upstream because it changes the request, not just the render.
  exposureRank?: ExposureRank;
  onChangeExposureRank?: (rank: ExposureRank) => void;
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
  mobile?: boolean;
}

function fmt(v: number | null, decimals = 1): string {
  if (v == null) return "—";
  return v.toLocaleString("en-US", { maximumFractionDigits: decimals });
}

// Shift factors are unitless and often small; 3 decimals keeps 0.03 legible.
function fmtSf(v: number | null): string {
  if (v == null) return "—";
  const sign = v >= 0 ? "+" : "−";
  return `${sign}${Math.abs(v).toFixed(3)}`;
}

// Max constraint-reach rows the card lists; the rest are summarized as a count
// (the map still glows the full footprint). 0147.
const REACH_ROW_CAP = 20;

function Row({
  label,
  value,
}: {
  label: string;
  value: string | number | null;
}) {
  return (
    <div className="dc-row">
      <span className="label">{label}</span>
      <span className="dc-val mono">{value ?? "—"}</span>
    </div>
  );
}

// Signed congestion $/MWh, e.g. "+$3.20/MWh" / "−$1.05/MWh". Null → "—".
// Bare signed magnitude for a column whose header already states $/MWh —
// repeating the unit on every row is what crowded the card.
function fmtDollars(v: number): string {
  return `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}`;
}

function fmtCong(v: number | null | undefined): string | null {
  if (v == null) return null;
  return `${v >= 0 ? "+" : "−"}$${fmt(Math.abs(v), 2)}/MWh`;
}

function SpBody({ sp }: { sp: HoveredSp }) {
  const s = sp.spState;
  return (
    <>
      <Row label="SP Type" value={String(sp.props.sp_type ?? "—")} />
      <Row label="Load Zone" value={String(sp.props.load_zone ?? "—")} />
      {/* forecast / realized / error — the decomposition carried in every view. */}
      <Row label="Forecast (P50) Congestion" value={fmtCong(s?.predicted)} />
      <Row label="Realized Congestion" value={fmtCong(s?.market)} />
      <Row label="Forecast Error" value={fmtCong(s?.error)} />
      <Row
        label="Predicted LMP"
        value={
          s && s.predictedSpp != null ? `$${fmt(s.predictedSpp, 2)}/MWh` : null
        }
      />
      <Row
        label="DAM LMP"
        value={s && s.marketSpp != null ? `$${fmt(s.marketSpp, 2)}/MWh` : null}
      />
    </>
  );
}

// The colored block identifies the constraint's structural type. SF already has
// an explicit signed numeric column, so encoding its sign in the block was
// redundant and made type harder to scan.
const TYPE_TOKENS: Record<string, string> = {
  gtc: "--sf-gtc",
  transmission: "--sf-transmission",
  radial: "--sf-radial",
};

function TypeChip({ ctype }: { ctype?: string | null }) {
  return (
    <span
      className="dc-chip"
      style={{
        background: `var(${TYPE_TOKENS[ctype ?? ""] ?? "--sf-untyped"})`,
      }}
      aria-hidden="true"
    />
  );
}

// Settlement points use their own nodal identifier, regardless of which
// constraint is currently being explored.
function NodeChip() {
  return (
    <span
      className="dc-chip"
      style={{ background: "var(--violet)" }}
      aria-hidden="true"
    />
  );
}

// The signed, colored value carries the direction on its own; a separate dot
// beside it said the same thing twice and cost a grid column.
function SfSign({ sf }: { sf: number }) {
  return (
    <span className="dc-driver-sf mono" style={{ color: shiftFactorColor(sf) }}>
      {fmtSf(sf)}
    </span>
  );
}

// Node-explorer body. Two bases, named on screen (0145): "Drove this hour"
// ranks by contribution (−SF × μ) and omits constraints that did not bind,
// answering what actually moved this node; "Exposure" ranks by |SF| over the
// whole day's fit, answering what could move it. They read identical SF values
// — showing which one is active is what keeps the card from looking like it
// disagrees with the matrix.
function ExposuresBody({
  exposures,
  loading,
  rank,
  onChangeRank,
  cursorTs,
  onSelectConstraint,
  onHoverConstraint,
}: {
  exposures: ExposuresResponse | null;
  loading?: boolean;
  rank: ExposureRank;
  onChangeRank?: (rank: ExposureRank) => void;
  cursorTs?: Date;
  onSelectConstraint?: (c: string) => void;
  onHoverConstraint?: (c: string | null) => void;
}) {
  const byContribution = rank === "contribution";
  // Same format as the scrubber and the matrix, so the card is visibly pinned
  // to the same instant the rest of the workspace is showing.
  const hour = cursorTs ? `${formatCT(cursorTs, "MMM d, HH:mm")} CT` : null;
  const header = (
    <div className="dc-drivers-head">
      <span className="dc-drivers-basis label">
        {byContribution
          ? hour
            ? `Drove ${hour}`
            : "Drove this hour"
          : "Exposure"}
      </span>
      {onChangeRank && (
        <button
          className="dc-drivers-toggle label"
          onClick={() => onChangeRank(byContribution ? "sf" : "contribution")}
          title={
            byContribution
              ? "Show every constraint this node is structurally exposed to, ranked by |SF| — including those that did not bind."
              : "Show only the constraints that actually drove this node at this hour, ranked by −SF × μ."
          }
        >
          {byContribution ? "exposure" : "drivers"}
        </button>
      )}
    </div>
  );

  if (!exposures) {
    return (
      <>
        {header}
        <div className="dc-drivers-empty label">
          {loading ? "loading drivers…" : "—"}
        </div>
      </>
    );
  }
  const total = exposures.node_total;
  return (
    <>
      {header}
      {exposures.exposures.length === 0 && (
        <div className="dc-drivers-empty label">
          {byContribution
            ? "Nothing bound this hour"
            : "No constraints in this fit"}
        </div>
      )}
      <div
        className="dc-drivers"
        onMouseLeave={() => onHoverConstraint?.(null)}
      >
        {/* Column headers carry the units, so the rows carry bare numbers. The
            key column is `constraint|contingency` — the artifact's own key
            order (services/sf_artifacts.normalize_constraint_key).

            It lives *inside* the scroll container, stuck to the top, so it is
            subject to the same scrollbar the rows are. Outside it, a classic
            (space-taking) scrollbar squeezes the rows ~12px narrower than the
            header and every numeric column reads as shifted right — invisible
            under macOS/headless overlay scrollbars, plainly wrong elsewhere. */}
        {exposures.exposures.length > 0 && (
          <div className="dc-driver dc-driver--head">
            <span aria-hidden="true" />
            <span className="dc-driver-col label">
              Constraint | Contingency
            </span>
            <span className="dc-driver-col label">
              {byContribution ? "$/MWh" : "SF"}
            </span>
            <span className="dc-driver-col label">
              {byContribution ? "Share" : "Binding"}
            </span>
          </div>
        )}
        {exposures.exposures.map((e) => (
          <button
            key={e.constraint_key}
            className="dc-driver"
            onClick={() => onSelectConstraint?.(e.constraint_key)}
            onMouseEnter={() => onHoverConstraint?.(e.constraint_key)}
            title={
              e.sf_clipped
                ? `SF is pinned at the fit's ±1 clip — a bound on a poorly-conditioned column, not a measured 1:1 response.`
                : undefined
            }
          >
            <TypeChip ctype={e.ctype} />
            <span className="dc-driver-key mono">
              {e.constraint_key}
              {e.sf_clipped && <span className="dc-driver-clip">*</span>}
            </span>
            {byContribution && e.contribution != null ? (
              <>
                <span
                  className="dc-driver-sf mono"
                  style={{ color: shiftFactorColor(-e.contribution) }}
                >
                  {fmtDollars(e.contribution)}
                </span>
                {/* Share of the node's full congestion, not of the visible
                    top-k — node_total sums every constraint. */}
                <span className="dc-driver-sup mono">
                  {total
                    ? `${Math.round((e.contribution / total) * 100)}%`
                    : "—"}
                </span>
              </>
            ) : (
              <>
                <SfSign sf={e.sf} />
                <span className="dc-driver-sup mono">
                  {e.binding_hours != null ? `${e.binding_hours}h` : "—"}
                </span>
              </>
            )}
          </button>
        ))}
      </div>
      {exposures.exposures.some((e) => e.sf_clipped) && (
        <div className="dc-drivers-note label">
          * SF pinned at the fit's ±1 clip — a bound, not a measurement
        </div>
      )}
    </>
  );
}

// Constraint-reach body: which nodes this constraint drives, split into the
// import (SF<0) and export (SF>0) ends (docs/SF.md).
function ReachBody({
  reach,
  onHoverMember,
  onSelectMember,
}: {
  reach: ConstraintReach;
  onHoverMember?: (sp: string | null) => void;
  onSelectMember?: (sp: string) => void;
}) {
  const importEnd = reach.sps.filter((s) => s.sf < 0).length;
  const exportEnd = reach.sps.filter((s) => s.sf >= 0).length;
  return (
    <>
      {reach.basis === "nearest_past" && (
        <div className="dc-support label">
          SF as of {reach.window_start.slice(0, 10)} — no artifact for the
          selected day
        </div>
      )}
      <Row
        label="Binding hours"
        value={reach.binding_hours != null ? `${reach.binding_hours} h` : null}
      />
      <Row label="Import nodes" value={importEnd} />
      <Row label="Export nodes" value={exportEnd} />
      <div
        className="dc-drivers dc-drivers--reach"
        onMouseLeave={() => onHoverMember?.(null)}
      >
        {/* The map glows the constraint's full driven footprint (0147); the card
            lists the strongest REACH_ROW_CAP and reports the rest as a count, so a
            broad constraint's hundreds of members stay scannable here. */}
        <div className="dc-driver dc-driver--head dc-driver--reach-row">
          <span aria-hidden="true" />
          <span className="dc-driver-col label">Settlement Point</span>
          <span className="dc-driver-col label">SF</span>
        </div>
        {reach.sps.slice(0, REACH_ROW_CAP).map((s) => (
          <button
            key={s.settlement_point}
            className="dc-driver dc-driver--reach-row"
            onClick={() => onSelectMember?.(s.settlement_point)}
            onMouseEnter={() => onHoverMember?.(s.settlement_point)}
          >
            <NodeChip />
            <span className="dc-driver-key mono">{s.settlement_point}</span>
            <SfSign sf={s.sf} />
          </button>
        ))}
        {reach.sps.length > REACH_ROW_CAP && (
          <div className="dc-support label">
            + {reach.sps.length - REACH_ROW_CAP} more nodes
          </div>
        )}
      </div>
    </>
  );
}

export default function DetailCard({
  hoveredSp,
  pinnedSp,
  exposures,
  exposuresLoading,
  exposureRank,
  onChangeExposureRank,
  cursorTs,
  reach,
  onClose,
  onCloseReach,
  onSelectConstraint,
  onHoverConstraint,
  onHoverMember,
  onSelectMember,
  showDrivers = true,
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
          />
        ) : (
          <>
            <SpBody sp={sp!} />
            {isPinned && showDrivers && !noSfLabel && (
              <div className="detail-card__section">
                <ExposuresBody
                  exposures={exposures ?? null}
                  loading={exposuresLoading}
                  rank={exposureRank ?? "contribution"}
                  onChangeRank={onChangeExposureRank}
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
        .dc-drivers-toggle {
          font-size: 11px;
          color: var(--text-secondary);
          background: transparent;
          border: 1px solid var(--border);
          border-radius: 3px;
          padding: 1px 5px;
          cursor: pointer;
        }
        .dc-drivers-toggle:hover {
          color: var(--text);
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
          padding-top: 6px;
          border-top: 1px solid var(--border);
        }
        /* One grid for the header row and every driver row, so the columns line
           up in both bases. Four columns: type chip, key, value, support.
           The numeric tracks are fixed widths, not auto: each row is its own
           grid container, so auto sizes every row to its own content and the
           header drifts out of line with the values under it. */
        .dc-driver {
          display: grid;
          grid-template-columns: 10px 1fr 58px 46px;
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
        /* Reach rows carry no support column, so they end at the value. */
        .dc-driver--reach-row {
          grid-template-columns: 10px 1fr 58px;
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
