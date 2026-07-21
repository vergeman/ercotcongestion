import { useState, Fragment } from "react";
import type { ScoreboardHeadline, RankedConstraints } from "../../api/types";
import ConstraintPanel from "./ConstraintPanel";

// The right-hand side panel, hosting two tabs in one region (plan/0103): `Stats`
// (0102) — a compact network readout over the rolling backtest scorecard — and
// `Constraints` (0103) — the per-day ranked constraint list. One region, tabbed;
// never a second panel. The scorecard's one rule (spec §6): a model figure never
// renders alone — each row shows the model, the persistence baseline it must beat,
// and the oracle ceiling, with the model↔persistence leader bolded so "did we beat
// the baseline" reads at a glance.

export interface NetworkStats {
  forecastRunId: string | null;
  systemLambda: number | null; // DAM system-λ at the cursor hour ($/MWh)
  congestionAbsTotal: number | null; // Σ|congestion| at the cursor hour ($)
  modelNodes: number; // SPs the forecast values this hour
  ercotNodes: number; // SPs ERCOT realized values this hour
}

interface Props {
  network: NetworkStats;
  // The rolling headline, or null on 503 (no board loaded) — the scorecard then
  // hides and the network readout stands alone.
  headline: ScoreboardHeadline | null;
  // ── Constraints tab (plan/0103) ──────────────────────────────────────────
  ranked: RankedConstraints | null;
  rankedLoading: boolean;
  constraintBasis: "predicted" | "realized";
  onConstraintBasis: (b: "predicted" | "realized") => void;
  // Synced hover (Group 4): the constraint the map is isolating, and the callback
  // a hovered row fires. Optional so the panel works before the sync is wired.
  highlightedConstraintId?: string | null;
  onHoverConstraint?: (id: string | null) => void;
  onSelectConstraint?: (id: string) => void;
  // A constituent SP hovered in an expanded row — App rings that node on the map.
  onMemberHover?: (sp: string | null) => void;
}

function fmtNum(v: number | null, decimals = 1): string {
  if (v == null) return "—";
  return v.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

// Two decimals, uniform across currencies so the table reads as a grid of
// comparable figures (top-decile / sign are hit-rates, rank ρ a correlation —
// all live in ~[0,1]).
const fmtScore = (v: number | null): string => (v == null ? "—" : v.toFixed(2));

// The three headline currencies (screening leads; §6) with per-row hover copy.
const CURRENCY_ORDER = ["topdecile_hit", "rank_spearman", "sign_agree"] as const;
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
    label: "Sign",
    hint: "Sign agreement: fraction of nodes whose congestion sign (import vs export) the forecast gets right.",
  },
};

// Which of model / persistence leads for this currency's orientation. Oracle is
// the ceiling reference, not a competitor, so it is never the "leader".
function leaderOf(
  model: number | null,
  persist: number | null,
  higher: boolean
): "model" | "persist" | null {
  if (model == null || persist == null || model === persist) return null;
  const modelWins = higher ? model > persist : model < persist;
  return modelWins ? "model" : "persist";
}

function Stat({ label, value, hint }: { label: string; value: string | number | null; hint?: string }) {
  return (
    <div className="np-stat">
      <span className="label" title={hint}>{label}</span>
      <span className="np-stat__val mono">{value ?? "—"}</span>
    </div>
  );
}

export default function SidePanel({
  network,
  headline,
  ranked,
  rankedLoading,
  constraintBasis,
  onConstraintBasis,
  highlightedConstraintId,
  onHoverConstraint,
  onSelectConstraint,
  onMemberHover,
}: Props) {
  const [windowDays, setWindowDays] = useState<number>(30);
  const [tab, setTab] = useState<"stats" | "constraints">("stats");
  const win =
    headline?.windows.find((w) => w.window_days === windowDays) ??
    headline?.windows[0] ??
    null;
  const byCurrency = new Map(win?.currencies.map((c) => [c.currency, c]) ?? []);

  return (
    <aside className="side-panel">
      {/* ── Tab bar: one region, two questions (plan/0103) ─────────────── */}
      <div className="sp-tabs" role="tablist" aria-label="side panel">
        {(["stats", "constraints"] as const).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            className={`sp-tab${tab === t ? " active" : ""}`}
            onClick={() => setTab(t)}
          >
            {t === "stats" ? "Stats" : "Constraints"}
          </button>
        ))}
      </div>

      {tab === "constraints" ? (
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
        <Stat label="Forecast Run" value={network.forecastRunId} />
        <Stat
          label="DAM System λ"
          value={network.systemLambda != null ? `$${fmtNum(network.systemLambda, 2)}/MWh` : null}
        />
        <Stat
          label="‖Congestion‖ (hr)"
          value={network.congestionAbsTotal != null ? `$${fmtNum(network.congestionAbsTotal, 0)}` : null}
        />
        <Stat
          label="Nodes (model/ercot)"
          hint="Settlement points with a value at the cursor hour: model forecast vs ERCOT realized. The model forecasts its full nodal universe; ERCOT lights only nodes with a published price that day — so a few resource nodes (RN / CC / PUN) are model-only, and model ≥ ercot."
          value={network.modelNodes || network.ercotNodes ? `${network.modelNodes} / ${network.ercotNodes}` : null}
        />
      </section>

      {/* ── Scorecard headline (compact table) ────────────────────────── */}
      {headline && win && (
        <section className="np-section">
          <div className="np-section__header sc-header">
            <span className="label">Scorecard · Backtest</span>
            <div className="sc-window-toggle">
              {[30, 90].map((d) => (
                <button
                  key={d}
                  className={windowDays === d ? "active" : ""}
                  onClick={() => setWindowDays(d)}
                >
                  {d}D
                </button>
              ))}
            </div>
          </div>

          <div className="sc-meta label">
            {win.weeks} wk · as of {headline.as_of_week} · {headline.regime}
          </div>

          <div className="sc-table">
            <span className="sc-h sc-h--cat" />
            <span className="sc-h">model</span>
            <span className="sc-h">persist</span>
            <span className="sc-h">ceiling</span>

            {CURRENCY_ORDER.map((name) => {
              const cur = byCurrency.get(name);
              const meta = CURRENCY_META[name];
              if (!cur || !meta) return null;
              const lead = leaderOf(cur.model, cur.persistence, cur.higher_is_better);
              return (
                <Fragment key={name}>
                  <span className="sc-cat label" title={meta.hint}>
                    {meta.label}
                  </span>
                  <span className="sc-v mono" data-lead={lead === "model"}>
                    {fmtScore(cur.model)}
                  </span>
                  <span className="sc-v mono" data-lead={lead === "persist"}>
                    {fmtScore(cur.persistence)}
                  </span>
                  <span className="sc-v sc-v--ceiling mono" title="Oracle ceiling — the best any forecast could do on these weeks.">
                    {fmtScore(cur.oracle)}
                  </span>
                </Fragment>
              );
            })}
          </div>

          <a className="sc-link" href="/scoreboard">
            View full scoreboard →
          </a>
        </section>
      )}
        </>
      )}

      <style>{`
        .side-panel {
          width: var(--panel-w);
          flex-shrink: 0;
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
          font-size: 12px;
          letter-spacing: var(--track-label);
          text-transform: uppercase;
          cursor: pointer;
        }
        .sp-tab:hover { color: var(--text-secondary); }
        .sp-tab.active {
          color: var(--text-primary);
          border-bottom-color: var(--accent);
        }
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
        .np-stat__val { font-size: 12px; color: var(--text-primary); }

        .sc-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        .sc-window-toggle { display: flex; gap: 4px; }
        .sc-window-toggle button {
          padding: 2px 7px;
          font-size: 10px;
          font-family: var(--font-label);
          letter-spacing: var(--track-label);
        }
        .sc-meta { margin-bottom: 8px; color: var(--text-muted); }

        .sc-table {
          display: grid;
          grid-template-columns: 1fr 3em 3em 3em;
          column-gap: 8px;
          row-gap: 5px;
          align-items: baseline;
        }
        .sc-h {
          font-size: 9px;
          font-family: var(--font-label);
          letter-spacing: var(--track-label);
          text-transform: uppercase;
          color: var(--text-muted);
          text-align: right;
        }
        .sc-h--cat { text-align: left; }
        .sc-cat {
          cursor: help;
          border-bottom: 1px dotted var(--text-muted);
          justify-self: start;
        }
        .sc-v {
          font-size: 13px;
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
          font-size: 11px;
          color: var(--accent);
          text-decoration: none;
          font-family: var(--font-label);
          letter-spacing: normal;
        }
        .sc-link:hover { text-decoration: underline; }
      `}</style>
    </aside>
  );
}
