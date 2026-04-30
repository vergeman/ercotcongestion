import type { SnapshotMeta, BusState } from '../types';

interface Props {
  meta: SnapshotMeta | null;
  hoveredBus: { busId: string; props: Record<string, unknown>; busState: BusState | null } | null;
}

function Stat({ label, value }: { label: string; value: string | number | null }) {
  return (
    <div className="stat">
      <span className="label">{label}</span>
      <span className="stat__val mono">{value ?? '—'}</span>
    </div>
  );
}

function fmt(v: number | null, decimals = 1): string {
  if (v == null) return '—';
  return v.toLocaleString('en-US', { maximumFractionDigits: decimals });
}

export default function StatsPanel({ meta, hoveredBus }: Props) {
  return (
    <div className="stats-panel">
      <div className="panel-section">
        <div className="panel-section__header label">System State</div>
        {meta ? (
          <>
            <Stat label="Load" value={meta.total_load_mw != null ? `${fmt(meta.total_load_mw)} MW` : null} />
            <Stat label="Gen" value={meta.total_gen_mw != null ? `${fmt(meta.total_gen_mw)} MW` : null} />
            <Stat label="Binding Lines" value={meta.n_binding_lines} />
            <Stat label="Obj Cost" value={meta.objective_cost != null ? `$${fmt(meta.objective_cost, 0)}` : null} />
            <Stat label="Fragility Total" value={meta.fragility_total != null ? fmt(meta.fragility_total, 3) : null} />
            <Stat label="Top-10 Share" value={meta.fragility_top10_share != null ? `${fmt(meta.fragility_top10_share * 100, 1)}%` : null} />
          </>
        ) : (
          <div className="panel-empty label">no snapshot selected</div>
        )}
      </div>

      {meta && (
        <div className="panel-section">
          <div className="panel-section__header label">LMP Range</div>
          <div className="lmp-range">
            <div className="lmp-item">
              <span className="label">min</span>
              <span className="mono" style={{ color: '#3b82f6' }}>${fmt(meta.lmp_min)}</span>
            </div>
            <div className="lmp-item">
              <span className="label">avg</span>
              <span className="mono">${fmt(meta.lmp_mean)}</span>
            </div>
            <div className="lmp-item">
              <span className="label">max</span>
              <span className="mono" style={{ color: '#ef4444' }}>${fmt(meta.lmp_max)}</span>
            </div>
          </div>
        </div>
      )}

      {meta && (meta.binding_lines?.length ?? 0) > 0 && (
        <div className="panel-section">
          <div className="panel-section__header label">Binding Constraints</div>
          <div className="list-items">
            {meta.binding_lines.slice(0, 5).map((bl) => (
              <div key={bl.line} className="list-item">
                <span className="mono" style={{ fontSize: 11 }}>{bl.line}</span>
                <span className="mono" style={{ color: '#f59e0b', fontSize: 11 }}>
                  ${fmt(bl.shadow_price, 1)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {meta && (meta.top_contingencies?.length ?? 0) > 0 && (
        <div className="panel-section">
          <div className="panel-section__header label">Top N-1 Contingencies</div>
          <div className="list-items">
            {meta.top_contingencies.map((c) => (
              <div key={c.line} className="list-item">
                <span className="mono" style={{ fontSize: 11 }}>{c.line}</span>
                <span className="mono" style={{ color: '#ef4444', fontSize: 11 }}>
                  {fmt(c.stress, 2)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {meta && Object.keys(meta.dispatch_by_carrier).length > 0 && (
        <div className="panel-section">
          <div className="panel-section__header label">Dispatch by Carrier</div>
          {Object.entries(meta.dispatch_by_carrier)
            .sort(([, a], [, b]) => b - a)
            .slice(0, 6)
            .map(([carrier, mw]) => (
              <div key={carrier} className="dispatch-row">
                <span className="dispatch-label label">{carrier}</span>
                <div className="dispatch-bar-wrap">
                  <div
                    className="dispatch-bar"
                    style={{
                      width: `${Math.min(100, (mw / (meta.total_gen_mw || 1)) * 100)}%`,
                      background: carrierColor(carrier),
                    }}
                  />
                </div>
                <span className="mono" style={{ fontSize: 10, color: 'var(--text-secondary)', minWidth: 60, textAlign: 'right' }}>
                  {fmt(mw, 0)} MW
                </span>
              </div>
            ))}
        </div>
      )}

      {hoveredBus && (
        <div className="panel-section panel-section--hovered">
          <div className="panel-section__header label">Bus Detail</div>
          <Stat label="Bus ID" value={hoveredBus.busId} />
          <Stat label="Load Zone" value={String(hoveredBus.props.load_zone ?? '—')} />
          <Stat label="Weather Zone" value={String(hoveredBus.props.weather_zone ?? '—')} />
          <Stat label="Voltage" value={hoveredBus.props.voltage != null ? `${hoveredBus.props.voltage} kV` : null} />
          {hoveredBus.busState && (
            <>
              <Stat label="Fragility" value={hoveredBus.busState.fragility != null ? fmt(hoveredBus.busState.fragility, 4) : null} />
              <Stat label="LMP" value={hoveredBus.busState.lmp != null ? `$${fmt(hoveredBus.busState.lmp, 2)}/MWh` : null} />
            </>
          )}
        </div>
      )}

      <style>{`
        .stats-panel {
          width: var(--panel-w);
          height: 100%;
          overflow-y: auto;
          background: var(--bg-panel);
          border-left: 1px solid var(--border);
          display: flex;
          flex-direction: column;
          gap: 0;
        }
        .panel-section {
          padding: 12px 14px;
          border-bottom: 1px solid var(--border);
        }
        .panel-section--hovered {
          background: var(--bg-hover);
          border-top: 1px solid var(--accent-dim);
        }
        .panel-section__header {
          margin-bottom: 8px;
          color: var(--text-secondary);
        }
        .panel-empty {
          color: var(--text-muted);
          font-style: italic;
          font-size: 11px;
        }
        .stat {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 3px 0;
        }
        .stat__val { font-size: 12px; color: var(--text-primary); }
        .lmp-range {
          display: flex;
          gap: 0;
        }
        .lmp-item {
          flex: 1;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 2px;
          padding: 4px 0;
        }
        .lmp-item .mono { font-size: 11px; }
        .list-items { display: flex; flex-direction: column; gap: 2px; }
        .list-item {
          display: flex;
          justify-content: space-between;
          padding: 2px 0;
          border-bottom: 1px solid var(--border);
        }
        .dispatch-row {
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 3px 0;
        }
        .dispatch-label { min-width: 52px; color: var(--text-secondary); }
        .dispatch-bar-wrap {
          flex: 1;
          height: 6px;
          background: var(--border);
          border-radius: 3px;
          overflow: hidden;
        }
        .dispatch-bar {
          height: 100%;
          border-radius: 3px;
          transition: width 0.3s;
        }
      `}</style>
    </div>
  );
}

function carrierColor(carrier: string): string {
  const map: Record<string, string> = {
    wind: '#38bdf8',
    solar: '#fbbf24',
    gas: '#f97316',
    nuclear: '#a78bfa',
    coal: '#78716c',
    hydro: '#34d399',
    oil: '#f43f5e',
  };
  const key = carrier.toLowerCase();
  for (const [k, c] of Object.entries(map)) {
    if (key.includes(k)) return c;
  }
  return '#8899aa';
}
