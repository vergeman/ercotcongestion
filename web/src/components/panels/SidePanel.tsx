import { useState, Fragment, type ReactNode } from "react";
import type {
  MapScorecard,
  RankedConstraints,
  MapFitMetadata,
  ConditionsEntry,
} from "../../api/types";
import ConstraintPanel from "./ConstraintPanel";
import Tooltip from "../ui/Tooltip";
import { formatCT } from "../../lib/time";
import { fmtNum, fmtScore } from "../../lib/format";

// Map sidebar with Stats and Constraints tabs.

export interface NetworkStats {
  forecastRunId: string | null;
  systemLambda: number | null; // DAM system-λ at the cursor hour ($/MWh)
  congestionAbsTotal: number | null; // Σ|congestion| at the cursor hour ($)
  modelNodes: number; // SPs the forecast values this hour
  ercotNodes: number; // SPs ERCOT realized values this hour
}

interface Props {
  network: NetworkStats;
  // DAM-close load, wind, solar, and outage conditions for the cursor hour.
  conditions: ConditionsEntry | null;
  scorecard: MapScorecard | null;
  fitMeta: MapFitMetadata | null;
  // ── Constraints tab ─────────────────────────────────────────────────────
  ranked: RankedConstraints | null;
  rankedLoading: boolean;
  constraintBasis: "predicted" | "realized";
  onConstraintBasis: (b: "predicted" | "realized") => void;
  // Synced hover: the constraint currently isolated on the map.
  highlightedConstraintId?: string | null;
  onHoverConstraint?: (id: string | null) => void;
  onSelectConstraint?: (id: string) => void;
  onMemberHover?: (sp: string | null) => void;
  variant?: "sidebar" | "drawer";
  loadWindow?: ReactNode;
}

const CURRENCY_ORDER = [
  "rank_spearman",
  "sign_agree",
  "topdecile_hit",
] as const;
const CURRENCY_META: Record<string, { label: string; hint: string }> = {
  topdecile_hit: {
    label: "Top-Decile",
    hint: "Top-decile hit rate: share of the worst-congested decile of nodes the forecast flags. Chance ≈ 0.10; a flat forecast is declined and cannot score.",
  },
  rank_spearman: {
    label: "Rank ρ",
    hint: "Spatial Spearman rank correlation of the forecast to realized congestion across nodes.",
  },
  sign_agree: {
    label: "Sign Agreement",
    hint: "Sign agreement: fraction of nodes whose congestion sign (import vs export) the forecast gets right.",
  },
};

function leaderOf(
  model: number | null,
  persist: number | null,
  higher: boolean
): "model" | "persist" | null {
  if (model == null || persist == null || model === persist) return null;
  const modelWins = higher ? model > persist : model < persist;
  return modelWins ? "model" : "persist";
}

function scorecardLabel(scorecard: MapScorecard): string {
  switch (scorecard.basis) {
    case "served_daily":
      return `Final served · ${scorecard.delivery_date}`;
    case "served_daily_pending":
      return "Final score pending";
    case "weekly_backtest_fallback":
      return `Historical backtest · week of ${scorecard.scored_week}`;
    default:
      return "No score available";
  }
}

// ERCOT load weather zones and wind/solar generation regions.
const WEATHER_ZONES = [
  "coast",
  "east",
  "far_west",
  "north",
  "north_central",
  "south_central",
  "southern",
  "west",
] as const;
const WIND_REGIONS = [
  "panhandle",
  "coastal",
  "south",
  "west",
  "north",
] as const;
const SOLAR_REGIONS = [
  "centerwest",
  "northwest",
  "farwest",
  "fareast",
  "southeast",
  "centereast",
] as const;
// ERCOT NP1-346 outage capacity by fuel.
const OUTAGE_FUELS = [
  "gas",
  "wind",
  "solar",
  "coal",
  "other",
  "hydro",
] as const;

const REGION_PRETTY: Record<string, string> = {
  far_west: "Far West",
  north_central: "North Central",
  south_central: "South Central",
  centerwest: "Center West",
  farwest: "Far West",
  fareast: "Far East",
  centereast: "Center East",
  system: "System",
  total: "Total",
};
function regionLabel(key: string): string {
  if (REGION_PRETTY[key]) return REGION_PRETTY[key];
  return key
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function conditionMw(
  row: { dam_close_mw: number | null } | undefined
): number | null {
  return row?.dam_close_mw ?? null;
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string | number | null;
  hint?: string;
}) {
  return (
    <div className="np-stat">
      <Tooltip className="label" tip={hint}>
        {label}
      </Tooltip>
      <span className="np-stat__val mono">{value ?? "—"}</span>
    </div>
  );
}

// A System total row that expands to its regions.
function ExpandableGroup({
  label,
  systemValue,
  rows,
  expanded,
  onToggle,
}: {
  label: string;
  systemValue: string | null;
  rows: { key: string; label: string; value: string | null }[];
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <div className="np-group">
      <button
        type="button"
        className="np-stat np-stat--toggle"
        onClick={onToggle}
        aria-expanded={expanded}
      >
        <span className="label">
          <span
            className={`np-caret${expanded ? " open" : ""}`}
            aria-hidden="true"
          >
            ▸
          </span>
          {label}
        </span>
        <span className="np-stat__val mono">{systemValue ?? "—"}</span>
      </button>
      {expanded &&
        rows.map((r) => <Stat key={r.key} label={r.label} value={r.value} />)}
    </div>
  );
}

export default function SidePanel({
  network,
  conditions,
  scorecard,
  fitMeta,
  ranked,
  rankedLoading,
  constraintBasis,
  onConstraintBasis,
  highlightedConstraintId,
  onHoverConstraint,
  onSelectConstraint,
  onMemberHover,
  variant = "sidebar",
  loadWindow,
}: Props) {
  const [tab, setTab] = useState<"stats" | "constraints" | "window">("stats");
  // Load-by-region / Generation panels (plan/0141): each System row discloses
  // its own regions independently — collapsed by default, one flag per group.
  const [regionsOpen, setRegionsOpen] = useState({
    load: false,
    wind: false,
    solar: false,
    outages: false,
  });
  const toggleRegions = (group: keyof typeof regionsOpen) =>
    setRegionsOpen((cur) => ({ ...cur, [group]: !cur[group] }));
  const bySeries = new Map(
    scorecard?.sources.map((source) => [source.series_id, source]) ?? []
  );
  const tabs = loadWindow
    ? (["stats", "constraints", "window"] as const)
    : (["stats", "constraints"] as const);

  return (
    <aside className={`side-panel side-panel--${variant}`}>
      {/* ── Tab bar: one region, two questions (plan/0103) ─────────────── */}
      <div className="sp-tabs" role="tablist" aria-label="side panel">
        {tabs.map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            className={`sp-tab${tab === t ? " active" : ""}`}
            onClick={() => setTab(t)}
          >
            {t === "stats"
              ? "Stats"
              : t === "constraints"
              ? "Constraints"
              : "Load window"}
          </button>
        ))}
      </div>

      {tab === "window" && loadWindow ? (
        <section className="sp-load-window">{loadWindow}</section>
      ) : tab === "constraints" ? (
        <ConstraintPanel
          ranked={ranked}
          loading={rankedLoading}
          basis={constraintBasis}
          onBasis={onConstraintBasis}
          highlightedId={highlightedConstraintId}
          onHover={onHoverConstraint}
          onSelect={onSelectConstraint}
          onMemberHover={onMemberHover}
        />
      ) : (
        <>
          {/* ── Network readout ───────────────────────────────────────────── */}
          <section className="np-section">
            <div className="np-section__header label">Network</div>
            <Stat
              label="DAM System λ"
              value={
                network.systemLambda != null
                  ? `$${fmtNum(network.systemLambda, 2)}/MWh`
                  : null
              }
            />
            <Stat
              label="Congestion Total (hr)"
              value={
                network.congestionAbsTotal != null
                  ? `$${fmtNum(network.congestionAbsTotal, 0)}`
                  : null
              }
            />
            <Stat
              label="Nodes (Forecast / ERCOT)"
              hint="Settlement points with a value at the cursor hour: model forecast vs ERCOT realized. The model forecasts its full nodal universe; ERCOT lights only nodes with a published price that day — so a few resource nodes (RN / CC / PUN) are model-only, and model ≥ ercot."
              value={
                network.modelNodes || network.ercotNodes
                  ? `${network.modelNodes} / ${network.ercotNodes}`
                  : null
              }
            />
          </section>

          {/* ── Conditions: Load / Wind / Solar / Outages (plan/0141) ────────
              One section, four roll-up rows — each category's own name IS the
              toggle row (no separate "System" child, no per-category header),
              so there is nothing to put a divider between except the section
              itself. Outages is a different quantity from Generation (MW
              offline vs. MW produced) but stays a peer row here; the label
              text carries that distinction, not a sub-grouping. */}
          <section className="np-section">
            <Tooltip
              className="np-section__header label"
              tip="Load and generation forecasts plus reported outage expectations available before the D-1 10:00 CT DAM close. Shared across Map views; not delivered actuals."
            >
              Conditions
            </Tooltip>
            <ExpandableGroup
              label="Load by Region"
              systemValue={(() => {
                const mw = conditionMw(
                  conditions?.load.find((z) => z.zone === "system")
                );
                return mw != null ? `${fmtNum(mw, 0)} MW` : null;
              })()}
              expanded={regionsOpen.load}
              onToggle={() => toggleRegions("load")}
              rows={WEATHER_ZONES.map((zone) => {
                const mw = conditionMw(
                  conditions?.load.find((z) => z.zone === zone)
                );
                return {
                  key: zone,
                  label: regionLabel(zone),
                  value: mw != null ? `${fmtNum(mw, 0)} MW` : null,
                };
              })}
            />
            <ExpandableGroup
              label="Wind Generation"
              systemValue={(() => {
                const mw = conditionMw(
                  conditions?.wind.find((r) => r.region === "system")
                );
                return mw != null ? `${fmtNum(mw, 0)} MW` : null;
              })()}
              expanded={regionsOpen.wind}
              onToggle={() => toggleRegions("wind")}
              rows={WIND_REGIONS.map((region) => {
                const mw = conditionMw(
                  conditions?.wind.find((r) => r.region === region)
                );
                return {
                  key: region,
                  label: regionLabel(region),
                  value: mw != null ? `${fmtNum(mw, 0)} MW` : null,
                };
              })}
            />
            <ExpandableGroup
              label="Solar Generation"
              systemValue={(() => {
                const mw = conditionMw(
                  conditions?.solar.find((r) => r.region === "system")
                );
                return mw != null ? `${fmtNum(mw, 0)} MW` : null;
              })()}
              expanded={regionsOpen.solar}
              onToggle={() => toggleRegions("solar")}
              rows={SOLAR_REGIONS.map((region) => {
                const mw = conditionMw(
                  conditions?.solar.find((r) => r.region === region)
                );
                return {
                  key: region,
                  label: regionLabel(region),
                  value: mw != null ? `${fmtNum(mw, 0)} MW` : null,
                };
              })}
            />
            <ExpandableGroup
              label="Outages by Fuel"
              systemValue={(() => {
                const mw = conditionMw(
                  conditions?.outages.find((f) => f.fuel === "total")
                );
                return mw != null ? `${fmtNum(mw, 0)} MW` : null;
              })()}
              expanded={regionsOpen.outages}
              onToggle={() => toggleRegions("outages")}
              rows={OUTAGE_FUELS.map((fuel) => {
                const mw = conditionMw(
                  conditions?.outages.find((f) => f.fuel === fuel)
                );
                return {
                  key: fuel,
                  label: regionLabel(fuel),
                  value: mw != null ? `${fmtNum(mw, 0)} MW` : null,
                };
              })}
            />
          </section>

          {/* ── Day-scoped scorecard (compact table) ───────────────────────── */}
          {scorecard && (
            <section className="np-section">
              <div className="np-section__header sc-header">
                <span className="label">Scorecard</span>
              </div>
              <div className="sc-meta label">{scorecardLabel(scorecard)}</div>

              <div className="sc-table">
                <span className="sc-h sc-h--cat" />
                <span className="sc-h">Model</span>
                <span className="sc-h">Persist</span>
                <span className="sc-h">Benchmark</span>

                {CURRENCY_ORDER.map((name) => {
                  const metric = name as
                    | "rank_spearman"
                    | "sign_agree"
                    | "topdecile_hit";
                  const meta = CURRENCY_META[name];
                  if (!meta) return null;
                  const model = bySeries.get("model")?.[metric] ?? null;
                  const persistence =
                    bySeries.get("persistence")?.[metric] ?? null;
                  const oracle = bySeries.get("oracle")?.[metric] ?? null;
                  const lead = leaderOf(model, persistence, true);
                  return (
                    <Fragment key={name}>
                      <Tooltip className="sc-cat label" tip={meta.hint}>
                        {meta.label}
                      </Tooltip>
                      <span className="sc-v mono" data-lead={lead === "model"}>
                        {fmtScore(model)}
                      </span>
                      <span
                        className="sc-v mono"
                        data-lead={lead === "persist"}
                      >
                        {fmtScore(persistence)}
                      </span>
                      <Tooltip
                        className="sc-v sc-v--ceiling mono"
                        tip="Settled-μ benchmark through the selected SF map; it is not a mathematical ceiling."
                      >
                        {fmtScore(oracle)}
                      </Tooltip>
                    </Fragment>
                  );
                })}
              </div>

              {fitMeta && (
                <div className="sc-fit">
                  <div className="sc-fit__header label">
                    SF Window
                    {fitMeta.window_start && fitMeta.window_end
                      ? ` · ${formatCT(
                          new Date(fitMeta.window_start),
                          "MMM d, yyyy"
                        )} – ${formatCT(
                          new Date(fitMeta.window_end),
                          "MMM d, yyyy"
                        )}`
                      : " · unavailable"}
                  </div>
                  {fitMeta.basis === "nearest_past" &&
                    fitMeta.artifact_delivery_date && (
                      <div className="sc-fit__note">
                        Fallback artifact from {fitMeta.artifact_delivery_date};
                        diagnostics use its SF window.
                      </div>
                    )}
                  <Stat
                    label="SF Out-of-sample Accuracy"
                    hint="R² explains % variation of this week's (held out) nodal congestion, and evaluates the Shift Factor matrix accuracy: the SF fit uses ERCOT's realized shadow prices (μ) to calculate implied congestion, compared with realized (ERCOT-settled) nodal congestion. Higher is better; 0 is an average-only baseline, and negative is worse. A new or rarely binding constraint with large μ can drastically lower this value because it has no fitted SF row."
                    value={fmtScore(fitMeta.sf_oos_r2)}
                  />
                  <Stat
                    label="SF Stability"
                    hint="Pearson correlation: how closely the SF values repeat when refit on a fresh, non-overlapping window. Higher means a steadier map. Measures changing SF values, not the set of constraints."
                    value={fmtScore(fitMeta.sf_stability)}
                  />
                </div>
              )}

              <a
                className="sc-link"
                href="/scoreboard"
                target="_blank"
                rel="noopener noreferrer"
              >
                View full scoreboard →
              </a>
            </section>
          )}
        </>
      )}

      <style>{`
        .side-panel {
          /* Map area is flex:5, this panel flex:2 → ~2/7 width (just under a
             third). --panel-w is a floor so the scorecard stays readable when narrow. */
          flex: 2 1 0;
          min-width: var(--panel-w);
          height: 100%;
          overflow-y: auto;
          background: var(--bg-panel);
          border-left: 1px solid var(--border);
          padding: 12px 14px 20px;
        }
        .sp-tabs {
          display: flex;
          gap: 4px;
          margin-bottom: 14px;
          border-bottom: 1px solid var(--border);
        }
        .sp-tab {
          padding: 6px 10px;
          background: none;
          border: none;
          border-bottom: 2px solid transparent;
          color: var(--text-muted);
          font-family: var(--font-label);
          font-weight: var(--fw-label);
          font-size: 13px;
          letter-spacing: var(--track-label);
          cursor: pointer;
        }
        .sp-tab:hover { color: var(--text-secondary); }
        .sp-tab.active {
          color: var(--text-primary);
          border-bottom-color: var(--accent);
        }
        .sp-load-window { padding-top: 2px; }
        .sp-tab:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
        .np-section { margin-bottom: 18px; }
        .np-section__header {
          padding-bottom: 6px;
          margin-bottom: 8px;
          border-bottom: 1px solid var(--border);
        }
        .np-stat {
          display: flex;
          justify-content: space-between;
          align-items: baseline;
          padding: 3px 0;
        }
        /* Bump the row labels above the global 11px --fs-label: the readout
           and scorecard row keys ("Forecast Run", "Top-Decile") read too small
           against their value cells. Scoped to this panel only. */
        .np-stat .label { font-size: 12.5px; }
        .np-stat__val { font-size: 13px; color: var(--text-primary); }

        /* Expandable System-total groups (plan/0141): the toggle row is a
           <button> styled as a Stat row, so it reads identically to every
           other row until the caret hints it opens. Disclosed region rows sit
           indented underneath, reusing the plain Stat row unchanged. */
        .np-group { margin-bottom: 2px; }
        .np-stat--toggle {
          width: 100%;
          background: none;
          border: none;
          cursor: pointer;
          font: inherit;
          text-align: inherit;
        }
        .np-stat--toggle .label { display: flex; align-items: center; gap: 5px; }
        .np-caret {
          display: inline-block;
          font-size: 9px;
          color: var(--text-muted);
          transition: transform 0.12s ease;
        }
        .np-caret.open { transform: rotate(90deg); }
        .np-group .np-stat:not(.np-stat--toggle) { padding-left: 15px; }

        .sc-header { display: flex; justify-content: space-between; align-items: center; }
        .sc-meta { margin: -1px 0 8px; color: var(--text-muted); }
        .sc-fit { margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--border); }
        .sc-fit__header { margin-bottom: 3px; color: var(--text-secondary); }

        .sc-table {
          display: grid;
          grid-template-columns: 1fr 3em 3em 3em;
          column-gap: 8px;
          row-gap: 5px;
          align-items: baseline;
        }
        .sc-h {
          font-size: 12px;
          font-family: var(--font-label);
          font-weight: var(--fw-label);
          letter-spacing: var(--track-label);
          color: var(--text-muted);
          text-align: right;
        }
        .sc-h--cat { text-align: left; }
        .sc-cat {
          cursor: help;
          border-bottom: 1px dotted var(--text-muted);
          justify-self: start;
          font-size: 12.5px;
        }
        .sc-v {
          font-size: 14px;
          text-align: right;
          color: var(--text-secondary);
          font-weight: 400;
        }
        /* the model↔persistence leader, bolded */
        .sc-v[data-lead="true"] { color: var(--text-primary); font-weight: 700; }
        .sc-v--ceiling { color: var(--text-muted); }

        .sc-link {
          display: inline-block;
          margin-top: 12px;
          font-size: 12px;
          color: var(--accent);
          text-decoration: none;
          font-family: var(--font-label);
          letter-spacing: normal;
        }
        .sc-link:hover { text-decoration: underline; }
        @media (max-width: 767px) {
          .side-panel--sidebar { display: none; }
          .side-panel--drawer {
            display: block;
            width: auto;
            min-width: 0;
            height: auto;
            overflow: visible;
            padding: 0;
            border: 0;
            background: transparent;
          }
        }
      `}</style>
    </aside>
  );
}
