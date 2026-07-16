import type { ExposuresResponse, ConstraintReach } from "../../api/types";
import { modeledCongestionColor } from "../../lib/colors";

interface HoveredSp {
  spId: string;
  props: Record<string, unknown>;
  spState: {
    congestion: number | null;
    spp: number | null;
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

function pct2(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toFixed(2);
}

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

function SpBody({ sp }: { sp: HoveredSp }) {
  return (
    <>
      <Row label="SP Type" value={String(sp.props.sp_type ?? "—")} />
      <Row label="Load Zone" value={String(sp.props.load_zone ?? "—")} />
      <Row
        label="Congestion"
        value={
          sp.spState && sp.spState.congestion != null
            ? `${sp.spState.congestion >= 0 ? "+" : "−"}$${fmt(
                Math.abs(sp.spState.congestion),
                2
              )}/MWh`
            : null
        }
      />
      <Row
        label="DAM SPP"
        value={
          sp.spState && sp.spState.spp != null
            ? `$${fmt(sp.spState.spp, 2)}/MWh`
            : null
        }
      />
    </>
  );
}

// The window confidence that qualifies every signed SF below it (spec §6):
// a flickering attribution should read as low-confidence, never as fact.
function Confidence({
  oosR2,
  sfStability,
}: {
  oosR2: number | null | undefined;
  sfStability: number | null | undefined;
}) {
  return (
    <div className="dc-conf label">
      fit R² {pct2(oosR2)} · SF stability {pct2(sfStability)}
    </div>
  );
}

// A signed-SF sign chip (blue export end ↔ red import end) — matches the map's
// diverging reach palette so the card and the glow agree.
function SignChip({ sf }: { sf: number }) {
  return (
    <span
      className="dc-chip"
      style={{ background: modeledCongestionColor(sf >= 0 ? 1 : -1) }}
    />
  );
}

// Node-explorer body: the stable unsigned magnitude leads; the signed
// per-constraint drivers follow as caveated detail (spec §6).
function ExposuresBody({
  exposures,
  loading,
  onSelectConstraint,
}: {
  exposures: ExposuresResponse | null;
  loading?: boolean;
  onSelectConstraint?: (c: string) => void;
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
      <Confidence
        oosR2={exposures.oos_r2}
        sfStability={exposures.sf_stability}
      />
      <div className="dc-headline">
        <span className="label">max exposure |SF|</span>
        <span className="dc-headline-val mono">
          {exposures.node_max_abs_sf != null
            ? exposures.node_max_abs_sf.toFixed(3)
            : "—"}
        </span>
      </div>
      <div className="dc-drivers-title label">
        top drivers · signed (read vs confidence)
      </div>
      {exposures.exposures.length === 0 && (
        <div className="dc-drivers-empty label">no binding constraints</div>
      )}
      <div className="dc-drivers">
        {exposures.exposures.map((e) => (
          <button
            key={e.constraint_key}
            className="dc-driver"
            onClick={() => onSelectConstraint?.(e.constraint_key)}
            title={`${e.constraint_key} — trace reach`}
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
// export (−) and import (+) ends.
function ReachBody({
  reach,
}: {
  reach: ConstraintReach;
}) {
  const exportEnd = reach.sps.filter((s) => s.sf < 0).length;
  const importEnd = reach.sps.filter((s) => s.sf >= 0).length;
  return (
    <>
      <Confidence oosR2={reach.oos_r2} sfStability={reach.sf_stability} />
      <div className="dc-headline">
        <span className="label">constraint |SF| max</span>
        <span className="dc-headline-val mono">
          {reach.max_abs_sf != null ? reach.max_abs_sf.toFixed(3) : "—"}
        </span>
      </div>
      <div className="dc-drivers-title label">
        drives {reach.sps.length} nodes · {exportEnd} export / {importEnd} import
      </div>
      <div className="dc-drivers">
        {reach.sps.map((s) => (
          <div key={s.settlement_point} className="dc-driver dc-driver--static">
            <SignChip sf={s.sf} />
            <span className="dc-driver-key mono">{s.settlement_point}</span>
            <span className="dc-driver-sf mono">{fmtSf(s.sf)}</span>
          </div>
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
            <>
              <span className="detail-card__kind detail-card__kind--constraint label">
                📌 CONSTRAINT
              </span>
              <span className="detail-card__id mono">
                {reach!.constraint_key}
              </span>
            </>
          ) : (
            <>
              <span className="detail-card__kind label">
                {isPinned ? "📌 " : ""}
                SP
              </span>
              <span className="detail-card__id mono">{sp!.spId}</span>
            </>
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
          <ReachBody reach={reach!} />
        ) : (
          <>
            <SpBody sp={sp!} />
            {isPinned && (
              <div className="detail-card__section">
                <ExposuresBody
                  exposures={exposures ?? null}
                  loading={exposuresLoading}
                  onSelectConstraint={onSelectConstraint}
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
          background: rgba(15, 18, 23, 0.94);
          border: 1px solid var(--border-bright);
          border-radius: 4px;
          padding: 0;
          backdrop-filter: blur(6px);
          z-index: 10;
          box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
          font-size: 12px;
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
          font-size: 9px;
          letter-spacing: 0.1em;
        }
        .detail-card__kind--constraint { color: #c4b5fd; }
        .detail-card__id {
          font-size: 12px;
          color: var(--text-primary);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .detail-card__close {
          padding: 0;
          width: 20px;
          height: 20px;
          font-size: 16px;
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
          font-size: 11px;
          color: var(--text-primary);
        }
        .dc-conf {
          font-size: 9px;
          color: var(--text-secondary);
          opacity: 0.85;
          margin-bottom: 4px;
        }
        .dc-headline {
          display: flex;
          justify-content: space-between;
          align-items: baseline;
          padding: 2px 0 4px;
        }
        .dc-headline-val {
          font-size: 15px;
          color: var(--text-primary);
          font-weight: 600;
        }
        .dc-drivers-title {
          font-size: 9px;
          color: var(--text-secondary);
          opacity: 0.7;
          margin-bottom: 3px;
        }
        .dc-drivers-empty {
          font-size: 10px;
          color: var(--text-muted);
          padding: 2px 0;
        }
        .dc-drivers {
          display: flex;
          flex-direction: column;
          gap: 1px;
          max-height: 220px;
          overflow-y: auto;
        }
        .dc-driver {
          display: grid;
          grid-template-columns: 10px 1fr auto auto;
          align-items: center;
          gap: 6px;
          padding: 3px 4px;
          background: transparent;
          border: none;
          border-radius: 3px;
          text-align: left;
          width: 100%;
          cursor: pointer;
        }
        .dc-driver:hover { background: rgba(255, 255, 255, 0.05); }
        .dc-driver--static { cursor: default; }
        .dc-driver--static:hover { background: transparent; }
        .dc-chip {
          width: 9px;
          height: 9px;
          border-radius: 2px;
          flex-shrink: 0;
        }
        .dc-driver-key {
          font-size: 10px;
          color: var(--text-primary);
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }
        .dc-driver-sf {
          font-size: 10px;
          color: var(--text-secondary);
        }
        .dc-driver-sup {
          font-size: 9px;
          color: var(--text-muted);
          min-width: 30px;
          text-align: right;
        }
      `}</style>
    </div>
  );
}
