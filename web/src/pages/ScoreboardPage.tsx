import { useEffect, useMemo, useRef, useState } from "react";
import type {
  ScoreboardWeekly,
  ScoreboardHeadline,
  ScoreboardDaily,
  WeeklyPoint,
  DailyPoint,
} from "../api/types";
import {
  fetchScoreboardWeekly,
  fetchScoreboardHeadline,
  fetchScoreboardDaily,
} from "../api/client";
import HeaderNav from "../components/layout/HeaderNav";

// The full backtest scoreboard page (plan/0102 §0002, spec-phase3 §5). The board
// the panel's "View full scoreboard" link targets: headline tiles, the weekly
// metric-vs-baselines-vs-oracle series (screening default, magnitude behind a
// toggle), a coverage strip on the shared x-axis, and the pooled pre/post-RTC+B
// split with the pre-registered gate verdict. Reads scoreboard_weekly only —
// independent of the forecast run. Integrity (§6): a model figure never appears
// without persistence + oracle in frame.

// The four charted sources, in fixed identity order, colored from the dataviz
// reference palette's dark categorical slots 1–4 (validated on the panel
// surface). CVD sits at the permitted first-four floor, so the required
// secondary encoding ships too: a legend + direct end-labels on every line.
const SERIES = [
  { source: "model", label: "Model", color: "#3987e5" },
  { source: "persistence", label: "Persistence", color: "#008300" },
  { source: "climatology", label: "Climatology", color: "#d55181" },
  { source: "oracle", label: "Oracle", color: "#c98500" },
] as const;

type MetricKey =
  | "topdecile_hit"
  | "rank_spearman"
  | "sign_agree"
  | "pooled_r2"
  | "mae";

const METRICS: Record<
  MetricKey,
  {
    label: string;
    group: "screening" | "magnitude";
    fmt: (v: number) => string;
    domain: (vals: number[]) => [number, number];
    higher: boolean;
  }
> = {
  topdecile_hit: { label: "Top-Decile Hit", group: "screening", fmt: (v) => v.toFixed(2), domain: () => [0, 1], higher: true },
  rank_spearman: { label: "Rank ρ", group: "screening", fmt: (v) => v.toFixed(2), domain: () => [0, 1], higher: true },
  sign_agree: { label: "Sign Agreement", group: "screening", fmt: (v) => v.toFixed(2), domain: () => [0, 1], higher: true },
  pooled_r2: { label: "Pooled R²", group: "magnitude", fmt: (v) => v.toFixed(2), domain: (vals) => [Math.min(0, ...vals), Math.max(1, ...vals)], higher: true },
  mae: { label: "MAE ($/MWh)", group: "magnitude", fmt: (v) => `$${v.toFixed(1)}`, domain: (vals) => [0, Math.max(1, ...vals) * 1.05], higher: false },
};
const SCREENING: MetricKey[] = ["topdecile_hit", "rank_spearman", "sign_agree"];
const MAGNITUDE: MetricKey[] = ["pooled_r2", "mae"];

const REGIMES: { value: string; label: string }[] = [
  { value: "all", label: "All hours" },
  { value: "net_load_0", label: "Net-load Q1 (low)" },
  { value: "net_load_1", label: "Net-load Q2" },
  { value: "net_load_2", label: "Net-load Q3" },
  { value: "net_load_3", label: "Net-load Q4" },
  { value: "net_load_4", label: "Net-load Q5 (peak)" },
];

const SPLIT_LABELS: Record<string, string> = {
  all: "All weeks",
  pre_rtc_b: "Pre-RTC+B",
  post_rtc_b: "Post-RTC+B",
};

const fmtWeek = (w: string): string =>
  new Date(`${w}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });

const fmtDay = (d: string): string =>
  new Date(`${d}T00:00:00Z`).toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });

// ── the weekly series chart (hand-rolled SVG) ───────────────────────────────
function SeriesChart({
  points,
  metric,
  cutover,
}: {
  points: WeeklyPoint[];
  metric: MetricKey;
  cutover: string;
}) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(720);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const measure = () => setWidth(el.clientWidth);
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  const weeks = useMemo(
    () => Array.from(new Set(points.map((p) => p.week))).sort(),
    [points]
  );
  const byKey = useMemo(() => {
    const m = new Map<string, WeeklyPoint>();
    for (const p of points) m.set(`${p.week}|${p.source}`, p);
    return m;
  }, [points]);

  const meta = METRICS[metric];
  const valueAt = (i: number, source: string): number | null => {
    const p = byKey.get(`${weeks[i]}|${source}`);
    const v = p ? (p[metric] as number | null) : null;
    return v == null ? null : v;
  };

  const seriesVals = useMemo(
    () =>
      SERIES.map((s) => ({
        ...s,
        vals: weeks.map((_, i) => valueAt(i, s.source)),
      })),
    [weeks, byKey, metric] // eslint-disable-line react-hooks/exhaustive-deps
  );

  const allVals = seriesVals.flatMap((s) => s.vals.filter((v): v is number => v != null));
  const [dMin, dMax] = meta.domain(allVals);

  // Right margin holds the direct end-labels (Persistence / Climatology ≈ 80px
  // at the 11px label face) — keep it wide enough that they don't clip.
  const M = { t: 14, r: 116, b: 22, l: 42 };
  const H = 280;
  const plotW = Math.max(1, width - M.l - M.r);
  const plotH = H - M.t - M.b;
  const n = weeks.length;

  const x = (i: number) => M.l + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const y = (v: number) =>
    M.t + (dMax === dMin ? plotH / 2 : (1 - (v - dMin) / (dMax - dMin)) * plotH);

  const linePath = (vals: (number | null)[]): string => {
    let d = "";
    let pen = false;
    vals.forEach((v, i) => {
      if (v == null) {
        pen = false;
        return;
      }
      d += `${pen ? "L" : "M"}${x(i).toFixed(1)} ${y(v).toFixed(1)} `;
      pen = true;
    });
    return d.trim();
  };

  // last non-null point per series → the direct end-label (identity, not
  // color-alone), with a small vertical de-collision.
  type EndLabel = { color: string; label: string; y: number };
  const endLabels: EndLabel[] = [];
  for (const s of seriesVals) {
    for (let i = s.vals.length - 1; i >= 0; i--) {
      const v = s.vals[i];
      if (v != null) {
        endLabels.push({ color: s.color, label: s.label, y: y(v) });
        break;
      }
    }
  }
  endLabels.sort((a, b) => a.y - b.y);
  for (let i = 1; i < endLabels.length; i++) {
    if (endLabels[i].y - endLabels[i - 1].y < 12) endLabels[i].y = endLabels[i - 1].y + 12;
  }

  // RTC+B cutover → nearest week index.
  const cutIdx = weeks.findIndex((w) => w >= cutover);
  const zeroInDomain = dMin < 0 && dMax > 0;

  // x tick indices: a handful across the span.
  const tickIdx = n <= 1 ? [0] : [0, Math.floor(n / 4), Math.floor(n / 2), Math.floor((3 * n) / 4), n - 1];

  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const i = Math.round((mx / plotW) * (n - 1));
    setHover(Math.max(0, Math.min(n - 1, i)));
  };

  return (
    <div ref={wrapRef} className="sb-chart" style={{ position: "relative" }}>
      <svg width={width} height={H} role="img" aria-label={`${meta.label} by week`}>
        {/* y gridlines + labels */}
        {[dMin, (dMin + dMax) / 2, dMax].map((v, k) => (
          <g key={k}>
            <line x1={M.l} x2={M.l + plotW} y1={y(v)} y2={y(v)} stroke="var(--border)" strokeWidth={1} />
            <text x={M.l - 6} y={y(v) + 3} textAnchor="end" className="sb-axis">{meta.fmt(v)}</text>
          </g>
        ))}
        {zeroInDomain && (
          <line x1={M.l} x2={M.l + plotW} y1={y(0)} y2={y(0)} stroke="var(--text-muted)" strokeWidth={1} strokeDasharray="2 2" />
        )}

        {/* x ticks */}
        {tickIdx.map((i) => (
          <text key={i} x={x(i)} y={H - 6} textAnchor="middle" className="sb-axis">{fmtWeek(weeks[i])}</text>
        ))}

        {/* RTC+B cutover marker */}
        {cutIdx > 0 && (
          <g>
            <line x1={x(cutIdx)} x2={x(cutIdx)} y1={M.t} y2={M.t + plotH} stroke="var(--text-secondary)" strokeWidth={1} strokeDasharray="3 3" />
            <text x={x(cutIdx) + 3} y={M.t + 9} className="sb-axis sb-axis--mark">RTC+B</text>
          </g>
        )}

        {/* series lines */}
        {seriesVals.map((s) => (
          <path key={s.source} d={linePath(s.vals)} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        ))}

        {/* direct end-labels (secondary encoding for the CVD floor) */}
        {endLabels.map((e, k) => (
          <text key={k} x={M.l + plotW + 5} y={e.y + 3} className="sb-endlabel" fill={e.color}>{e.label}</text>
        ))}

        {/* hover guide + markers */}
        {hover != null && (
          <g>
            <line x1={x(hover)} x2={x(hover)} y1={M.t} y2={M.t + plotH} stroke="var(--border-bright)" strokeWidth={1} />
            {seriesVals.map((s) => {
              const v = s.vals[hover];
              return v == null ? null : (
                <circle key={s.source} cx={x(hover)} cy={y(v)} r={3.5} fill={s.color} stroke="var(--bg-panel)" strokeWidth={1.5} />
              );
            })}
          </g>
        )}

        {/* hover capture */}
        <rect x={M.l} y={M.t} width={plotW} height={plotH} fill="transparent"
          onMouseMove={onMove} onMouseLeave={() => setHover(null)} />
      </svg>

      {hover != null && (
        <div className="sb-tip" style={{ left: Math.min(x(hover) + 8, width - 132), top: M.t }}>
          <div className="sb-tip__wk">{fmtWeek(weeks[hover])}</div>
          {seriesVals.map((s) => {
            const v = s.vals[hover];
            return (
              <div key={s.source} className="sb-tip__row">
                <span className="sb-tip__dot" style={{ background: s.color }} />
                <span className="sb-tip__lbl">{s.label}</span>
                <span className="sb-tip__val">{v == null ? "—" : meta.fmt(v)}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── live per-delivery-day grade panel (plan/0102 §0004, spec-phase3 §5) ──────
// "How did yesterday's forecast do." Reads /scoreboard/daily (live grades of the
// SERVED forecast) — the live counterpart to the backtest tiles below. The day is
// selectable; each metric carries its persistence delta + oracle ceiling so a lone
// model figure can't be read (§6). Renders server-served values only — no grade is
// recomputed here. Same tile form + validated colors as HeadlineTiles, so the live
// half reads as one system with the backtest half.

// The four graded currencies foregrounded per day. All higher-is-better, so a
// positive model−persistence delta is the model winning (matches HeadlineTiles +
// the _CURRENCIES orientation the API pools on).
const LIVE_METRICS: { name: keyof DailyPoint; label: string }[] = [
  { name: "topdecile_hit", label: "Top-Decile Hit" },
  { name: "rank_spearman", label: "Rank ρ" },
  { name: "sign_agree", label: "Sign Agreement" },
  { name: "pooled_r2", label: "Pooled R²" },
];

function LiveGradePanel({ daily }: { daily: ScoreboardDaily }) {
  // Delivery days present, most-recent first — the selector's options and default.
  const days = useMemo(
    () => Array.from(new Set(daily.points.map((p) => p.delivery_date))).sort().reverse(),
    [daily]
  );
  const [day, setDay] = useState<string>(days[0]);
  // Keep the selection valid when the run's live history changes underneath us.
  const selected = days.includes(day) ? day : days[0];

  // The selected day's rows, keyed by source, so a tile can read model /
  // persistence / oracle for one metric.
  const bySource = useMemo(() => {
    const m = new Map<string, DailyPoint>();
    for (const p of daily.points) {
      if (p.delivery_date === selected) m.set(p.source, p);
    }
    return m;
  }, [daily, selected]);

  const model = bySource.get("model");
  const persistence = bySource.get("persistence");
  const oracle = bySource.get("oracle");
  const val = (row: DailyPoint | undefined, name: keyof DailyPoint): number | null => {
    const v = row ? (row[name] as number | null) : null;
    return v == null ? null : v;
  };

  return (
    <section className="sb-live">
      <div className="sb-live__head">
        <span className="sb-section-h label sb-live__h">Live · per-delivery-day grade</span>
        <select
          className="sb-regime sb-live__day"
          value={selected}
          onChange={(e) => setDay(e.target.value)}
          aria-label="Delivery day"
        >
          {days.map((d) => (
            <option key={d} value={d}>{fmtDay(d)}</option>
          ))}
        </select>
        <span className="sb-live__ctx label">
          {model?.n_nodes != null ? `${model.n_nodes} nodes` : ""}
          {model?.n_hours != null ? ` · ${model.n_hours} h` : ""}
        </span>
      </div>

      <div className="sb-tiles">
        {LIVE_METRICS.map((mk) => {
          const m = val(model, mk.name);
          const p = val(persistence, mk.name);
          const o = val(oracle, mk.name);
          const delta = m != null && p != null ? m - p : null;
          // All LIVE_METRICS are higher-is-better; a non-negative delta wins.
          const good = delta == null ? null : delta >= 0;
          return (
            <div key={mk.name} className="sb-tile">
              <div className="label">{mk.label}</div>
              <div className="sb-tile__model">{m == null ? "—" : m.toFixed(2)}</div>
              <div className="sb-tile__cmp">
                {good != null && (
                  <span className="sb-delta" data-good={good}>
                    {good ? "▲" : "▼"} vs persist {p == null ? "—" : p.toFixed(2)}
                  </span>
                )}
                <span className="sb-ceiling">ceiling {o == null ? "—" : o.toFixed(2)}</span>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ── headline tiles (reuse the 0001 endpoint — comparators ride along) ───────
function HeadlineTiles({ headline }: { headline: ScoreboardHeadline | null }) {
  const win = headline?.windows.find((w) => w.window_days === 90) ?? headline?.windows[0];
  if (!win) return null;
  const pick = (name: string) => win.currencies.find((c) => c.currency === name);
  const tiles = [
    { name: "topdecile_hit", label: "Top-Decile Hit" },
    { name: "rank_spearman", label: "Rank ρ" },
    { name: "sign_agree", label: "Sign Agreement" },
  ];
  return (
    <div className="sb-tiles">
      {tiles.map((t) => {
        const c = pick(t.name);
        if (!c) return null;
        const good = c.persistence_delta == null ? null : c.higher_is_better ? c.persistence_delta >= 0 : c.persistence_delta <= 0;
        return (
          <div key={t.name} className="sb-tile">
            <div className="label">{t.label}</div>
            <div className="sb-tile__model">{c.model == null ? "—" : c.model.toFixed(2)}</div>
            <div className="sb-tile__cmp">
              {good != null && (
                <span className="sb-delta" data-good={good}>{good ? "▲" : "▼"} vs persist {c.persistence == null ? "—" : c.persistence.toFixed(2)}</span>
              )}
              <span className="sb-ceiling">ceiling {c.oracle == null ? "—" : c.oracle.toFixed(2)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── pooled pre/post-RTC+B split table ───────────────────────────────────────
function SplitTable({ weekly, metric }: { weekly: ScoreboardWeekly; metric: MetricKey }) {
  const meta = METRICS[metric];
  const val = (label: string, source: string): number | null => {
    const sp = weekly.splits.find((s) => s.label === label)?.sources.find((x) => x.source === source);
    const v = sp ? (sp[metric] as number | null) : null;
    return v == null ? null : v;
  };
  return (
    <div className="sb-splits">
      <div className="sb-split-grid">
        <span className="sb-h" />
        {SERIES.map((s) => (
          <span key={s.source} className="sb-h" style={{ color: s.color }}>{s.label}</span>
        ))}

        {weekly.splits.map((sp) => {
          const m = val(sp.label, "model");
          const p = val(sp.label, "persistence");
          const modelLeads = m != null && p != null && m !== p && (meta.higher ? m > p : m < p);
          const persistLeads = m != null && p != null && m !== p && !modelLeads;
          return (
            <div key={sp.label} className="sb-split-row" style={{ display: "contents" }}>
              <span className="sb-cat label">{SPLIT_LABELS[sp.label] ?? sp.label} · {sp.n_weeks}w</span>
              <span className="sb-v" data-lead={modelLeads}>{m == null ? "—" : meta.fmt(m)}</span>
              <span className="sb-v" data-lead={persistLeads}>{p == null ? "—" : meta.fmt(p)}</span>
              <span className="sb-v">{(() => { const v = val(sp.label, "climatology"); return v == null ? "—" : meta.fmt(v); })()}</span>
              <span className="sb-v sb-v--ceiling">{(() => { const v = val(sp.label, "oracle"); return v == null ? "—" : meta.fmt(v); })()}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function ScoreboardPage() {
  const [regime, setRegime] = useState("all");
  const [group, setGroup] = useState<"screening" | "magnitude">("screening");
  const [metric, setMetric] = useState<MetricKey>("topdecile_hit");
  const [weekly, setWeekly] = useState<ScoreboardWeekly | null>(null);
  const [headline, setHeadline] = useState<ScoreboardHeadline | null>(null);
  const [daily, setDaily] = useState<ScoreboardDaily | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    setLoading(true);
    Promise.all([fetchScoreboardWeekly("model", regime), fetchScoreboardHeadline(regime)])
      .then(([w, h]) => {
        if (!live) return;
        setWeekly(w);
        setHeadline(h);
      })
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [regime]);

  // The live per-day board is a run-level surface, not sliced by the regime
  // selector — fetch it once. 503 → null so the panel is gracefully absent
  // before any live grade exists (the backtest board still renders).
  useEffect(() => {
    let live = true;
    fetchScoreboardDaily("model").then((d) => live && setDaily(d));
    return () => {
      live = false;
    };
  }, []);

  const chartWidth = weekly ? undefined : undefined; // width measured inside chart
  void chartWidth;

  // The rolling window the headline tiles summarize (same pick as HeadlineTiles):
  // surfaced in the topbar so the tiles aren't captioned by a stray note.
  const headlineWin =
    headline?.windows.find((w) => w.window_days === 90) ?? headline?.windows[0];

  return (
    <div className="sb-page">
      <header className="sb-topbar">
        <HeaderNav active="scoreboard" />
        <div className="sb-meta">
          <span
            className="sb-meta__label label"
            title="The model run whose backtest is scored on this page."
          >
            Backtest run
          </span>
          <span className="sb-meta__val">{weekly ? weekly.run_id : "—"}</span>
          {headlineWin && (
            <>
              <span className="sb-meta__sep">·</span>
              <span
                className="sb-meta__label label"
                title="The rolling window the headline tiles average over: the most recent graded weeks of the backtest. The week count changes with the regime filter."
              >
                Window
              </span>
              <span className="sb-meta__val">
                rolling {headlineWin.window_days}d · {headlineWin.weeks} wk
              </span>
            </>
          )}
        </div>
        <select className="sb-regime" value={regime} onChange={(e) => setRegime(e.target.value)}>
          {REGIMES.map((r) => (
            <option key={r.value} value={r.value}>{r.label}</option>
          ))}
        </select>
      </header>

      {/* The live half — rendered independently of the backtest board, and
          gracefully absent until a served day has been graded (§0004). */}
      {daily && <LiveGradePanel daily={daily} />}

      {loading && <div className="sb-empty label">loading…</div>}
      {!loading && !weekly && (
        <div className="sb-empty label">no board loaded for “{regime}”.</div>
      )}

      {weekly && (
        <>
          <HeadlineTiles headline={headline} />

          {/* metric controls: screening leads, magnitude behind a toggle */}
          <div className="sb-controls">
            <div className="sb-metric-group">
              {(group === "screening" ? SCREENING : MAGNITUDE).map((mk) => (
                <button key={mk} className={metric === mk ? "active" : ""} onClick={() => setMetric(mk)}>
                  {METRICS[mk].label}
                </button>
              ))}
            </div>
            <button
              className="sb-group-toggle"
              onClick={() => {
                const next = group === "screening" ? "magnitude" : "screening";
                setGroup(next);
                setMetric(next === "screening" ? "topdecile_hit" : "pooled_r2");
              }}
            >
              {group === "screening" ? "Show magnitude (R²/MAE) →" : "← Back to screening"}
            </button>
          </div>

          <SeriesChart points={weekly.points} metric={metric} cutover={weekly.rtc_b_cutover} />

          {/* legend — identity for ≥2 series, alongside the direct end-labels */}
          <div className="sb-legend">
            {SERIES.map((s) => (
              <span key={s.source} className="sb-legend__item">
                <i className="sb-legend__swatch" style={{ background: s.color }} /> {s.label}
              </span>
            ))}
            <span className="sb-legend__note">screening currency leads; magnitude is diagnostic (§6)</span>
          </div>

          <div className="sb-section-h label">Pooled · pre/post-RTC+B ({METRICS[metric].label})</div>
          <SplitTable weekly={weekly} metric={metric} />
        </>
      )}

      <style>{`
        .sb-page {
          height: 100%;
          overflow-y: auto;
          background: var(--bg-base);
          color: var(--text-primary);
          padding: 0 0 40px;
          /* One font on this page (Inter). Numbers used to be set in the mono
             face; tabular-nums keeps them column-aligned without a 2nd family. */
          font-variant-numeric: tabular-nums;
        }
        .sb-topbar {
          display: flex; align-items: center; gap: 14px;
          height: var(--header-h);
          padding: 0 16px;
          background: var(--bg-panel);
          border-bottom: 1px solid var(--border);
          position: sticky; top: 0; z-index: 2;
        }
        .sb-meta {
          margin-left: auto;
          display: flex;
          align-items: baseline;
          gap: 6px;
        }
        .sb-meta__label { color: var(--text-muted); cursor: help; }
        .sb-meta__val {
          font-family: var(--font-mono);
          font-size: 12px;
          color: var(--text-secondary);
        }
        .sb-meta__sep { color: var(--border-bright); }
        .sb-regime {
          background: var(--bg-surface); color: var(--text-primary);
          border: 1px solid var(--border); border-radius: 3px;
          padding: 4px 8px; font-size: 13px; font-family: inherit;
        }
        .sb-empty { padding: 40px 16px; text-align: center; }

        .sb-live { border-bottom: 1px solid var(--border); padding-bottom: 10px; }
        .sb-live__head { display: flex; align-items: center; gap: 12px; padding: 12px 16px 0; flex-wrap: wrap; }
        .sb-live__h { padding: 0; }
        .sb-live__day { margin-left: 0; }
        .sb-live__ctx { margin-left: auto; color: var(--text-muted); }

        .sb-tiles { display: flex; gap: 12px; padding: 12px 16px 4px; align-items: stretch; flex-wrap: wrap; }
        .sb-tile {
          flex: 1; min-width: 150px;
          background: var(--bg-panel); border: 1px solid var(--border);
          border-radius: 4px; padding: 8px 12px;
        }
        .sb-tile__model { font-size: 28px; font-weight: 700; line-height: 1.1; margin: 2px 0 4px; }
        .sb-tile__cmp { display: flex; flex-direction: column; gap: 2px; font-size: 12px; }
        .sb-delta { font-weight: 600; }
        .sb-delta[data-good="true"] { color: var(--ok); }
        .sb-delta[data-good="false"] { color: var(--danger); }
        .sb-ceiling { color: var(--text-secondary); }

        .sb-controls { display: flex; align-items: center; gap: 14px; padding: 10px 16px 6px; flex-wrap: wrap; }
        .sb-metric-group { display: flex; gap: 4px; }
        .sb-metric-group button, .sb-group-toggle { font-size: 12px; padding: 4px 10px; }
        .sb-group-toggle { color: var(--text-secondary); }

        .sb-chart { padding: 0 16px; }
        .sb-chart svg { display: block; width: 100%; }
        .sb-axis { fill: var(--text-muted); font-size: 10px; font-family: var(--font-sans); font-variant-numeric: tabular-nums; }
        .sb-axis--mark { fill: var(--text-secondary); font-family: var(--font-label); letter-spacing: normal; }
        .sb-endlabel { font-size: 11px; font-family: var(--font-label); font-weight: 600; }

        .sb-tip {
          position: absolute; pointer-events: none;
          background: rgba(15,18,23,0.94); border: 1px solid var(--border-bright);
          border-radius: 3px; padding: 5px 8px; font-size: 12px; min-width: 116px;
        }
        .sb-tip__wk { color: var(--accent); margin-bottom: 3px; font-size: 12px; }
        .sb-tip__row { display: flex; align-items: center; gap: 5px; }
        .sb-tip__dot { width: 7px; height: 7px; border-radius: 2px; flex-shrink: 0; }
        .sb-tip__lbl { color: var(--text-secondary); flex: 1; }
        .sb-tip__val { color: var(--text-primary); }

        .sb-cov { padding: 0 16px; margin-top: -4px; }

        .sb-legend { display: flex; gap: 14px; padding: 8px 16px 4px; align-items: center; flex-wrap: wrap; font-size: 12px; color: var(--text-secondary); }
        .sb-legend__item { display: flex; align-items: center; gap: 5px; }
        .sb-legend__swatch { width: 12px; height: 3px; border-radius: 1px; display: inline-block; }
        .sb-legend__note { color: var(--text-muted); font-size: 11px; }

        .sb-section-h { padding: 14px 16px 6px; }
        .sb-splits { padding: 0 16px; overflow-x: auto; }
        .sb-split-grid { display: inline-grid; grid-template-columns: minmax(180px, 260px) repeat(4, 108px); column-gap: 28px; row-gap: 10px; align-items: baseline; padding-right: 24px; }
        .sb-h { font-size: 12px; font-family: var(--font-label); letter-spacing: var(--track-label); color: var(--text-muted); text-align: right; }
        .sb-cat { text-align: left; font-size: 13px; }
        .sb-v { font-size: 16px; text-align: right; color: var(--text-secondary); }
        .sb-v[data-lead="true"] { color: var(--text-primary); font-weight: 700; }
        .sb-v--ceiling { color: var(--text-muted); }
      `}</style>
    </div>
  );
}
