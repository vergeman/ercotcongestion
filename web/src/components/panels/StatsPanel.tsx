import { useMemo } from "react";
import type { ScorecardResponse, SnapshotMeta } from "../../api/types";
import { clusterColor } from "../../lib/colors";

interface Props {
  meta: SnapshotMeta | null;
  scorecard: ScorecardResponse | null;
  selectedClusterId: number | null;
  onSelectCluster: (id: number | null) => void;
  showZones: boolean;
  onToggleZones: () => void;
}

function Stat({
  label,
  value,
}: {
  label: string;
  value: string | number | null;
}) {
  return (
    <div className="stat">
      <span className="label">{label}</span>
      <span className="stat__val mono">{value ?? "—"}</span>
    </div>
  );
}

function fmt(v: number | null, decimals = 1): string {
  if (v == null) return "—";
  return v.toLocaleString("en-US", { maximumFractionDigits: decimals });
}

function fmtPostingAge(postingTs: string | null): string {
  if (!postingTs) return "—";
  const posted = new Date(postingTs);
  const ageMs = Date.now() - posted.getTime();
  const ageH = ageMs / 3_600_000;
  if (ageH < 1) return `${Math.round(ageMs / 60_000)}m ago`;
  if (ageH < 48) return `${ageH.toFixed(1)}h ago`;
  return `${(ageH / 24).toFixed(1)}d ago`;
}

export default function StatsPanel({
  meta,
  scorecard,
  selectedClusterId,
  onSelectCluster,
  showZones,
  onToggleZones,
}: Props) {
  // Sort by corr desc, nulls last — this is the primary quality axis on the
  // scorecard, so a stable top-down ordering matches how a reader scans.
  const sortedZones = useMemo(() => {
    if (!scorecard) return [];
    return [...scorecard.zones].sort((a, b) => {
      const av = a.corr;
      const bv = b.corr;
      if (av == null && bv == null) return a.cluster_id - b.cluster_id;
      if (av == null) return 1;
      if (bv == null) return -1;
      return bv - av;
    });
  }, [scorecard]);
  const tightSet = useMemo(
    () => new Set(sortedZones.map((z) => z.cluster_id)),
    [sortedZones]
  );
  return (
    <div className="stats-panel">
      {scorecard && (
        <div className="panel-section">
          <div className="panel-section__header label">
            Cluster Scorecard · {scorecard.run_id}
          </div>
          <div className="scorecard-headline">
            <div className="scorecard-headline__item">
              <span className="label">rank ρ</span>
              <span className="mono">
                {fmt(scorecard.headline.rank_spearman, 2)}
              </span>
            </div>
            <div className="scorecard-headline__item">
              <span className="label">mean r</span>
              <span className="mono">
                {fmt(scorecard.headline.mean_corr, 2)}
              </span>
            </div>
            <div className="scorecard-headline__item">
              <span className="label">sign%</span>
              <span className="mono">
                {scorecard.headline.mean_sign_agreement != null
                  ? `${fmt(scorecard.headline.mean_sign_agreement * 100, 0)}%`
                  : "—"}
              </span>
            </div>
            <div className="scorecard-headline__item">
              <span className="label">hours</span>
              <span className="mono">{scorecard.headline.n_hours}</span>
            </div>
          </div>
          <button
            type="button"
            className={"zones-toggle label" + (showZones ? " active" : "")}
            onClick={onToggleZones}
          >
            {showZones ? "Toggle Zone Layers ✓" : "Toggle Zone Layers"}
          </button>
          <div className="scorecard-rows">
            <div className="scorecard-row scorecard-row--head label">
              <span>zone</span>
              <span>buses</span>
              <span>corr</span>
              <span>sign%</span>
              <span>disp</span>
            </div>
            {sortedZones.map((z) => {
              const selected = z.cluster_id === selectedClusterId;
              return (
                <div
                  key={z.cluster_id}
                  className={
                    "scorecard-row" +
                    (selected ? " scorecard-row--selected" : "")
                  }
                  onClick={() =>
                    onSelectCluster(selected ? null : z.cluster_id)
                  }
                >
                  <span
                    className="scorecard-row__zone mono"
                    style={{
                      ["--zone-color" as string]: clusterColor(
                        z.cluster_id,
                        tightSet
                      ),
                    }}
                  >
                    <span className="scorecard-row__swatch" />Z{z.cluster_id}
                  </span>
                  <span className="mono">{z.n_buses}</span>
                  <span className="mono">{fmt(z.corr, 2)}</span>
                  <span className="mono">
                    {z.sign_agreement != null
                      ? `${fmt(z.sign_agreement * 100, 0)}%`
                      : "—"}
                  </span>
                  <span className="mono">{fmt(z.model_side_std, 2)}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="panel-section">
        <div className="panel-section__header label">System State</div>
        {meta ? (
          <>
            <Stat
              label="Load"
              value={
                meta.total_load_mw != null
                  ? `${fmt(meta.total_load_mw)} MW`
                  : null
              }
            />
            <Stat
              label="Gen"
              value={
                meta.total_gen_mw != null
                  ? `${fmt(meta.total_gen_mw)} MW`
                  : null
              }
            />
            <Stat label="Binding Lines" value={meta.n_binding_lines} />
            <Stat
              label="Obj Cost"
              value={
                meta.objective_cost != null
                  ? `$${fmt(meta.objective_cost, 0)}`
                  : null
              }
            />
            <Stat
              label="‖Modeled Congestion‖"
              value={
                meta.modeled_congestion_abs_total != null
                  ? `$${fmt(meta.modeled_congestion_abs_total, 0)}`
                  : null
              }
            />
            <div className="stat stat--secondary">
              <span className="label">signed total</span>
              <span className="stat__val mono">
                {meta.modeled_congestion_total != null
                  ? `${meta.modeled_congestion_total >= 0 ? "+" : "−"}$${fmt(
                      Math.abs(meta.modeled_congestion_total),
                      0
                    )}`
                  : "—"}
              </span>
            </div>
            <Stat
              label="Top-10 Share"
              value={
                meta.modeled_congestion_top10_share != null
                  ? `${fmt(meta.modeled_congestion_top10_share * 100, 1)}%`
                  : null
              }
            />
            <div className="stat">
              <span className="label">Proximity Max</span>
              <span
                className="stat__val mono"
                style={
                  meta.binding_proximity_max != null &&
                  meta.binding_proximity_max >= 0.95
                    ? { color: "#ef4444", fontWeight: 600 }
                    : undefined
                }
              >
                {meta.binding_proximity_max != null
                  ? `${fmt(meta.binding_proximity_max * 100, 1)}%`
                  : "—"}
              </span>
            </div>
            <Stat
              label="Proximity P95"
              value={
                meta.binding_proximity_p95 != null
                  ? `${fmt(meta.binding_proximity_p95 * 100, 1)}%`
                  : null
              }
            />
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
              <span className="mono" style={{ color: "#3b82f6" }}>
                ${fmt(meta.lmp_min)}
              </span>
            </div>
            <div className="lmp-item">
              <span className="label">avg</span>
              <span className="mono">${fmt(meta.lmp_mean)}</span>
            </div>
            <div className="lmp-item">
              <span className="label">max</span>
              <span className="mono" style={{ color: "#ef4444" }}>
                ${fmt(meta.lmp_max)}
              </span>
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
                <span className="mono" style={{ fontSize: 11 }}>
                  {bl.line}
                </span>
                <span
                  className="mono"
                  style={{ color: "#ec4899", fontSize: 11 }}
                >
                  ${fmt(bl.shadow_price, 1)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {meta && (meta.top_contingencies?.length ?? 0) > 0 && (
        <div className="panel-section">
          <div className="panel-section__header label">
            Top N-1 Contingencies
          </div>
          <div className="list-items">
            {meta.top_contingencies.slice(0, 5).map((c) => (
              <div key={c.line} className="list-item">
                <span className="mono" style={{ fontSize: 11 }}>
                  {c.line}
                </span>
                <span
                  className="mono"
                  style={{ color: "#cbd5e1", fontSize: 11 }}
                >
                  {fmt(c.stress, 2)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {meta &&
        meta.outages_by_zone &&
        (() => {
          const zones = meta.outages_by_zone;
          const totalThermal = Object.values(zones).reduce(
            (s, z) => s + (z.thermal_mw ?? 0),
            0
          );
          const totalIrr = Object.values(zones).reduce(
            (s, z) => s + (z.irr_mw ?? 0),
            0
          );
          return (
            <div className="panel-section">
              <div className="panel-section__header label">
                Outages · {fmtPostingAge(meta.outage_posting_ts)}
              </div>
              <div className="outage-totals">
                <div className="outage-tot">
                  <span className="label">thermal</span>
                  <span className="mono" style={{ color: "#f97316" }}>
                    {fmt(totalThermal, 0)} MW
                  </span>
                </div>
                <div className="outage-tot">
                  <span className="label">irr</span>
                  <span className="mono" style={{ color: "#38bdf8" }}>
                    {fmt(totalIrr, 0)} MW
                  </span>
                </div>
              </div>
              <div className="outage-zones">
                {Object.entries(zones).map(([zone, vals]) => (
                  <div key={zone} className="outage-zone-row">
                    <span className="label">{zone}</span>
                    <span className="mono" style={{ fontSize: 11 }}>
                      <span style={{ color: "#f97316" }}>
                        {fmt(vals.thermal_mw, 0)}
                      </span>
                      <span style={{ color: "var(--text-muted)" }}> · </span>
                      <span style={{ color: "#38bdf8" }}>
                        {fmt(vals.irr_mw, 0)}
                      </span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          );
        })()}

      {meta && Object.keys(meta.dispatch_by_carrier).length > 0 && (
        <div className="panel-section">
          <div className="panel-section__header label">Dispatch by Carrier</div>
          {Object.entries(meta.dispatch_by_carrier)
            .sort(([, a], [, b]) => b - a)
            .slice(0, 5)
            .map(([carrier, mw]) => (
              <div key={carrier} className="dispatch-row">
                <span className="dispatch-label label">{carrier}</span>
                <div className="dispatch-bar-wrap">
                  <div
                    className="dispatch-bar"
                    style={{
                      width: `${Math.min(
                        100,
                        (mw / (meta.total_gen_mw || 1)) * 100
                      )}%`,
                      background: carrierColor(carrier),
                    }}
                  />
                </div>
                <span className="mono dispatch-mw">{fmt(mw, 0)} MW</span>
              </div>
            ))}
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
        }
        .panel-section {
          padding: 10px 12px;
          border-bottom: 1px solid var(--border);
        }
        .panel-section__header {
          margin-bottom: 6px;
          color: var(--text-secondary);
        }
        .zones-toggle {
          display: block;
          width: 100%;
          margin-bottom: 6px;
          background: transparent;
          color: var(--text-secondary);
          border: 1px solid var(--border);
          border-radius: 3px;
          padding: 6px 10px;
          font-family: 'Barlow Condensed', sans-serif;
          font-weight: 600;
          font-size: 12px;
          letter-spacing: 0.08em;
          text-transform: uppercase;
          cursor: pointer;
        }
        .zones-toggle:hover { color: var(--accent); }
        .zones-toggle.active {
          color: var(--accent);
          border-color: var(--accent);
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
          padding: 2px 0;
        }
        .stat__val { font-size: 11px; color: var(--text-primary); }
        .stat--secondary .label,
        .stat--secondary .stat__val {
          font-size: 10px;
          color: var(--text-muted);
        }
        .stat--secondary { padding-top: 0; margin-top: -2px; }

        .lmp-range { display: flex; }
        .lmp-item {
          flex: 1;
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 1px;
          padding: 3px 0;
        }
        .lmp-item .mono { font-size: 11px; }

        .list-items { display: flex; flex-direction: column; gap: 1px; }
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
          padding: 2px 0;
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
        .dispatch-mw {
          font-size: 10px;
          color: var(--text-secondary);
          min-width: 56px;
          text-align: right;
        }
        .outage-totals {
          display: flex;
          gap: 12px;
          padding: 2px 0 6px;
          border-bottom: 1px solid var(--border);
          margin-bottom: 4px;
        }
        .outage-tot { display: flex; flex-direction: column; gap: 1px; }
        .outage-tot .mono { font-size: 12px; }
        .outage-zones { display: flex; flex-direction: column; gap: 1px; }
        .outage-zone-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          padding: 2px 0;
        }
        .outage-zone-row .label { text-transform: capitalize; }

        .scorecard-headline {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 4px;
          padding: 2px 0 6px;
          border-bottom: 1px solid var(--border);
          margin-bottom: 4px;
        }
        .scorecard-headline__item {
          display: flex;
          flex-direction: column;
          gap: 1px;
          align-items: center;
        }
        .scorecard-headline__item .mono { font-size: 11px; }

        .scorecard-rows { display: flex; flex-direction: column; }
        .scorecard-row {
          display: grid;
          grid-template-columns: 1.1fr 0.8fr 0.9fr 0.9fr 0.9fr;
          gap: 4px;
          padding: 3px 4px;
          border-radius: 3px;
          cursor: pointer;
          font-size: 11px;
          color: var(--text-primary);
        }
        .scorecard-row .mono { font-size: 11px; text-align: right; }
        .scorecard-row .mono:first-child { text-align: left; }
        .scorecard-row:hover {
          background: var(--bg-base);
        }
        .scorecard-row--selected {
          background: var(--bg-base);
          box-shadow: inset 2px 0 0 var(--accent);
        }
        .scorecard-row--head {
          cursor: default;
          color: var(--text-secondary);
        }
        .scorecard-row--head:hover { background: transparent; }
        .scorecard-row--head span { text-align: right; }
        .scorecard-row--head span:first-child { text-align: left; }
        .scorecard-row__zone {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          text-align: left !important;
        }
        .scorecard-row__swatch {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: var(--zone-color, #64748b);
          box-shadow: 0 0 0 1px rgba(255,255,255,0.15);
        }
      `}</style>
    </div>
  );
}

function carrierColor(carrier: string): string {
  const map: Record<string, string> = {
    wind: "#38bdf8",
    solar: "#fbbf24",
    gas: "#f97316",
    nuclear: "#a78bfa",
    coal: "#78716c",
    hydro: "#34d399",
    oil: "#f43f5e",
  };
  const key = carrier.toLowerCase();
  for (const [k, c] of Object.entries(map)) {
    if (key.includes(k)) return c;
  }
  return "#8899aa";
}
