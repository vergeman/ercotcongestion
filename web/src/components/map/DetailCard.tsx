import type { SnapshotMeta, BusState } from "../../api/types";

interface HoveredBus {
  busId: string;
  props: Record<string, unknown>;
  busState: BusState | null;
}

interface HoveredLine {
  lineId: string;
  props: Record<string, unknown>;
}

interface HoveredSp {
  spId: string;
  props: Record<string, unknown>;
  spState: { congestion: number | null; spp: number | null } | null;
}

interface Props {
  meta: SnapshotMeta | null;
  hoveredBus: HoveredBus | null;
  hoveredLine: HoveredLine | null;
  pinnedBus?: HoveredBus | null;
  pinnedLine?: HoveredLine | null;
  hoveredSp?: HoveredSp | null;
  pinnedSp?: HoveredSp | null;
  onClose?: () => void;
}

function fmt(v: number | null, decimals = 1): string {
  if (v == null) return "—";
  return v.toLocaleString("en-US", { maximumFractionDigits: decimals }); /*  */
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

function BusBody({ bus }: { bus: HoveredBus }) {
  return (
    <>
      <Row label="Load Zone" value={String(bus.props.load_zone ?? "—")} />
      <Row label="Weather Zone" value={String(bus.props.weather_zone ?? "—")} />
      <Row
        label="Voltage"
        value={bus.props.voltage != null ? `${bus.props.voltage} kV` : null}
      />
      {bus.busState && (
        <>
          <Row
            label="Modeled Congestion"
            value={
              bus.busState.modeled_congestion != null
                ? `${bus.busState.modeled_congestion >= 0 ? "+" : "−"}$${fmt(
                    Math.abs(bus.busState.modeled_congestion),
                    2
                  )}/MWh`
                : null
            }
          />
          <Row
            label="Binding Proximity"
            value={
              bus.busState.binding_proximity != null
                ? `${fmt(bus.busState.binding_proximity * 100, 1)}%`
                : null
            }
          />
          <Row
            label="LMP"
            value={
              bus.busState.lmp != null
                ? `$${fmt(bus.busState.lmp, 2)}/MWh`
                : null
            }
          />
          <Row
            label="Basis"
            value={
              bus.busState.basis != null ? fmt(bus.busState.basis, 4) : null
            }
          />
        </>
      )}
    </>
  );
}

function SpBody({ sp }: { sp: HoveredSp }) {
  const clusterId = sp.props.cluster_id;
  return (
    <>
      <Row label="SP Type" value={String(sp.props.sp_type ?? "—")} />
      <Row label="Load Zone" value={String(sp.props.load_zone ?? "—")} />
      {clusterId != null && (
        <Row label="Cluster" value={String(clusterId)} />
      )}
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

function LineBody({
  line,
  meta,
}: {
  line: HoveredLine;
  meta: SnapshotMeta | null;
}) {
  const binding = meta?.binding_lines?.find((bl) => bl.line === line.lineId);
  const conts = meta?.top_contingencies ?? [];
  const contIdx = conts.findIndex((c) => c.line === line.lineId);
  const contingency = contIdx >= 0 ? conts[contIdx] : null;
  const sNom = line.props.s_nom != null ? Number(line.props.s_nom) : null;
  const length = line.props.length != null ? Number(line.props.length) : null;

  let statusLabel: string;
  if (contingency && contIdx < 5) {
    statusLabel = `⚠ N-1 #${contIdx + 1}`;
  } else if (binding) {
    statusLabel = "⚡ binding";
  } else {
    statusLabel = "normal";
  }

  return (
    <>
      <Row label="From" value={String(line.props.bus0 ?? "—")} />
      <Row label="To" value={String(line.props.bus1 ?? "—")} />
      <Row
        label="Capacity"
        value={sNom != null ? `${fmt(sNom, 0)} MVA` : null}
      />
      <Row
        label="Length"
        value={length != null ? `${fmt(length, 1)} km` : null}
      />
      <Row label="Status" value={statusLabel} />
      {binding && (
        <Row
          label="Shadow Price"
          value={`$${fmt(binding.shadow_price, 2)}/MWh`}
        />
      )}
      {contingency && (
        <Row label="Trip Stress" value={fmt(contingency.stress, 2)} />
      )}
    </>
  );
}

export default function DetailCard({
  meta,
  hoveredBus,
  hoveredLine,
  pinnedBus,
  pinnedLine,
  hoveredSp,
  pinnedSp,
  onClose,
}: Props) {
  // Pinned wins over hover. Bus wins over line if both present.
  // SP is its own selection stack (ERCOT pane) — independent of bus/line.
  const sp = pinnedSp ?? hoveredSp;
  const isPinned = !!(pinnedBus || pinnedLine || pinnedSp);
  const bus = !sp ? pinnedBus ?? hoveredBus : null;
  const line = !sp && !bus ? pinnedLine ?? hoveredLine : null;

  if (!sp && !bus && !line) return null;

  const id = sp ? sp.spId : bus ? bus.busId : line!.lineId;
  const kind = sp ? "SP" : bus ? "BUS" : "LINE";

  return (
    <div className={`detail-card ${isPinned ? "detail-card--pinned" : ""}`}>
      <div className="detail-card__header">
        <div className="detail-card__title">
          <span className="detail-card__kind label">
            {isPinned ? "📌 " : ""}
            {kind}
          </span>
          <span className="detail-card__id mono">{id}</span>
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
        {sp ? (
          <SpBody sp={sp} />
        ) : bus ? (
          <BusBody bus={bus} />
        ) : line ? (
          <LineBody line={line} meta={meta} />
        ) : null}
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
