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
  onClose?: () => void;
}

function fmt(v: number | null, decimals = 1): string {
  if (v == null) return "—";
  return v.toLocaleString("en-US", { maximumFractionDigits: decimals });
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

export default function DetailCard({ hoveredSp, pinnedSp, onClose }: Props) {
  // Pinned wins over hover.
  const sp = pinnedSp ?? hoveredSp;
  const isPinned = !!pinnedSp;

  if (!sp) return null;

  return (
    <div className={`detail-card ${isPinned ? "detail-card--pinned" : ""}`}>
      <div className="detail-card__header">
        <div className="detail-card__title">
          <span className="detail-card__kind label">
            {isPinned ? "📌 " : ""}
            SP
          </span>
          <span className="detail-card__id mono">{sp.spId}</span>
        </div>
        {isPinned && onClose && (
          <button
            className="detail-card__close"
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        )}
      </div>

      <div className="detail-card__body">
        <SpBody sp={sp} />
      </div>

      <style>{`
        .detail-card {
          position: absolute;
          top: 12px;
          left: 12px;
          width: 240px;
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
      `}</style>
    </div>
  );
}
