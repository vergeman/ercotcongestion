import type { ExposuresResponse, ConstraintReach } from "../../api/types";
import { congestionColor } from "../../lib/colors";

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
  } | null;
}

interface Props {
  hoveredSp?: HoveredSp | null;
  pinnedSp?: HoveredSp | null;
  // Top-k constraints driving the pinned SP (the node-explorer click). Loading
  // while null with a pinned SP; the card renders the SP body meanwhile.
  exposures?: ExposuresResponse | null;
  exposuresLoading?: boolean;
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

// Low-confidence is a shape verdict — mirror GridMap.tsx / docs §4. The artifact
// is the ridge clamp (>= RAIL_MULTI nodes co-equal at the ±1 cap, or a lone rail
// with no graded body beneath it), NOT a low hour count. binding_hours is a
// separate "thin support" caveat: clean-but-brief constraints are trustworthy.
const RAIL_MULTI = 2;
const BODY_FLOOR = 0.1;
const THIN_HOURS = 50;

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
      <Row label="Forecast (P50)" value={fmtCong(s?.predicted)} />
      <Row label="Realized" value={fmtCong(s?.market)} />
      <Row label="Forecast error" value={fmtCong(s?.error)} />
      <Row
        label="DAM SPP"
        value={
          s && s.marketSpp != null ? `$${fmt(s.marketSpp, 2)}/MWh` : null
        }
      />
    </>
  );
}

// A signed-SF sign chip (red import end SF<0 ↔ blue export end SF>0; docs/SF.md) —
// colored by congestion sign (−SF), so it matches the map's diverging reach glow
// and congestion fill: import is red, export is blue.
function SignChip({ sf }: { sf: number }) {
  return (
    <span
      className="dc-chip"
      style={{ background: congestionColor(sf < 0 ? 1 : -1) }}
    />
  );
}

// Node-explorer body: drivers are ordered by |SF|, so the first row already
// communicates the largest influence without a redundant headline statistic.
function ExposuresBody({
  exposures,
  loading,
  onSelectConstraint,
  onHoverConstraint,
}: {
  exposures: ExposuresResponse | null;
  loading?: boolean;
  onSelectConstraint?: (c: string) => void;
  onHoverConstraint?: (c: string | null) => void;
}) {
  if (!exposures) {
    return (
      <div className="dc-drivers-empty label">
        {loading ? "loading drivers…" : "—"}
      </div>
    );
  }
  return (
    <>
      {exposures.exposures.length === 0 && (
        <div className="dc-drivers-empty label">No binding constraints</div>
      )}
      <div
        className="dc-drivers"
        onMouseLeave={() => onHoverConstraint?.(null)}
      >
        {exposures.exposures.map((e) => (
          <button
            key={e.constraint_key}
            className="dc-driver"
            onClick={() => onSelectConstraint?.(e.constraint_key)}
            onMouseEnter={() => onHoverConstraint?.(e.constraint_key)}
          >
            <SignChip sf={e.sf} />
            <span className="dc-driver-key mono">{e.constraint_key}</span>
            <span className="dc-driver-sf mono">{fmtSf(e.sf)}</span>
            <span className="dc-driver-sup label">
              {e.binding_hours != null ? `${e.binding_hours}h` : "—"}
            </span>
          </button>
        ))}
      </div>
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
  const nRail = reach.n_rail ?? 0;
  // Ridge-clamp artifact: several nodes at the cap, or a lone rail with no body.
  const railArtifact =
    nRail >= RAIL_MULTI ||
    (nRail >= 1 &&
      (reach.peak_offrail == null || reach.peak_offrail < BODY_FLOOR));
  const thin =
    reach.binding_hours != null && reach.binding_hours < THIN_HOURS;
  const lowConf = railArtifact;
  return (
    <>
      <Row
        label="Binding hours"
        value={reach.binding_hours != null ? `${reach.binding_hours} h` : null}
      />
      <Row label="Import nodes" value={importEnd} />
      <Row label="Export nodes" value={exportEnd} />
      {(lowConf || thin) && (
        <div className={`dc-support label ${lowConf ? "dc-support--low" : ""}`}>
          {lowConf ? "⚠ low confidence — ridge clamp" : "thin support"}
        </div>
      )}
      <div
        className="dc-drivers dc-drivers--reach"
        onMouseLeave={() => onHoverMember?.(null)}
      >
        {reach.sps.map((s) => (
          <button
            key={s.settlement_point}
            className="dc-driver"
            onClick={() => onSelectMember?.(s.settlement_point)}
            onMouseEnter={() => onHoverMember?.(s.settlement_point)}
          >
            <SignChip sf={s.sf} />
            <span className="dc-driver-key mono">{s.settlement_point}</span>
            <span className="dc-driver-sf mono">{fmtSf(s.sf)}</span>
          </button>
        ))}
      </div>
    </>
  );
}

export default function DetailCard({
  hoveredSp,
  pinnedSp,
  exposures,
  exposuresLoading,
  reach,
  onClose,
  onCloseReach,
  onSelectConstraint,
  onHoverConstraint,
  onHoverMember,
  onSelectMember,
  showDrivers = true,
}: Props) {
  // Reach (constraint pinned) wins; otherwise pinned SP wins over hover.
  const inReach = !!reach;
  const sp = pinnedSp ?? hoveredSp;
  const isPinned = !!pinnedSp;

  if (!inReach && !sp) return null;

  return (
    <div className={`detail-card ${inReach || isPinned ? "detail-card--pinned" : ""}`}>
      <div className="detail-card__header">
        <div className="detail-card__title">
          {inReach ? (
            <span className="detail-card__id mono">{reach!.constraint_key}</span>
          ) : (
            <span className="detail-card__id mono">{sp!.spId}</span>
          )}
        </div>
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
            {isPinned && showDrivers && (
              <div className="detail-card__section">
                <ExposuresBody
                  exposures={exposures ?? null}
                  loading={exposuresLoading}
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
          width: 250px;
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
        .dc-support--low { color: var(--text-dim); }
        .dc-drivers-empty {
          font-size: 11px;
          color: var(--text-muted);
          padding: 2px 0;
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
        .dc-driver {
          display: grid;
          grid-template-columns: 10px 1fr auto auto;
          align-items: center;
          gap: 6px;
          padding: 3px 0;
          background: transparent;
          border: none;
          border-radius: 3px;
          text-align: left;
          width: 100%;
          cursor: pointer;
        }
        .dc-driver:hover { background: var(--bg-hover); }
        .dc-chip {
          width: 9px;
          height: 9px;
          border-radius: 2px;
          flex-shrink: 0;
        }
        .dc-driver-key {
          font-size: 11px;
          color: var(--text-primary);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .dc-driver-sf {
          font-size: 11px;
          color: var(--text-secondary);
        }
        .dc-driver-sup {
          font-size: 10px;
          color: var(--text-muted);
          min-width: 30px;
          text-align: right;
        }
      `}</style>
    </div>
  );
}
