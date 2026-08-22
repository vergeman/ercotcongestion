import { useMemo, useState } from "react";
import type {
  ScoreboardWeekly,
  ScoreboardHeadline,
  ScoreboardDaily,
  WeeklyPoint,
  DailyPoint,
  HeadlineWindow,
} from "../api/types";
import HeaderNav from "../components/layout/HeaderNav";
import HeaderStatus from "../components/layout/HeaderStatus";
import Tooltip from "../components/ui/Tooltip";
import { useScoreboard } from "../hooks/useScoreboard";
import {
  METRICS,
  ScoreboardControls,
  type MetricKey,
  useScoreboardControls,
} from "../features/scoreboard/ScoreboardControls";
import { useScoreboardChart } from "../features/scoreboard/useScoreboardChart";
import "../features/scoreboard/scoreboard.css";

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

  const allVals = seriesVals.flatMap((s) =>
    s.vals.filter((v): v is number => v != null)
  );
  const [dMin, dMax] = meta.domain(allVals);

  // Right margin holds the direct end-labels (Persistence / Climatology ≈ 80px
  // at the 11px label face) — keep it wide enough that they don't clip.
  const M = { t: 14, r: 116, b: 22, l: 42 };
  const H = 280;
  const n = weeks.length;
  const {
    wrapRef, width, hover, clearHover, moveHover, setHoverFromCoordinate,
  } = useScoreboardChart(n);
  const plotW = Math.max(1, width - M.l - M.r);
  const plotH = H - M.t - M.b;

  const x = (i: number) => M.l + (n <= 1 ? plotW / 2 : (i / (n - 1)) * plotW);
  const y = (v: number) =>
    M.t +
    (dMax === dMin ? plotH / 2 : (1 - (v - dMin) / (dMax - dMin)) * plotH);

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
    if (endLabels[i].y - endLabels[i - 1].y < 12)
      endLabels[i].y = endLabels[i - 1].y + 12;
  }

  // RTC+B cutover → nearest week index.
  const cutIdx = weeks.findIndex((w) => w >= cutover);
  const zeroInDomain = dMin < 0 && dMax > 0;

  // x tick indices: a handful across the span.
  const tickIdx =
    n <= 1
      ? [0]
      : [
          0,
          Math.floor(n / 4),
          Math.floor(n / 2),
          Math.floor((3 * n) / 4),
          n - 1,
        ];

  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    setHoverFromCoordinate(mx, plotW);
  };

  return (
    <div ref={wrapRef} className="sb-chart" style={{ position: "relative" }}>
      <svg
        width={width}
        height={H}
        role="img"
        aria-label={`${meta.label} by week`}
      >
        {/* y gridlines + labels */}
        {[dMin, (dMin + dMax) / 2, dMax].map((v, k) => (
          <g key={k}>
            <line
              x1={M.l}
              x2={M.l + plotW}
              y1={y(v)}
              y2={y(v)}
              stroke="var(--border)"
              strokeWidth={1}
            />
            <text x={M.l - 6} y={y(v) + 3} textAnchor="end" className="sb-axis">
              {meta.fmt(v)}
            </text>
          </g>
        ))}
        {zeroInDomain && (
          <line
            x1={M.l}
            x2={M.l + plotW}
            y1={y(0)}
            y2={y(0)}
            stroke="var(--text-muted)"
            strokeWidth={1}
            strokeDasharray="2 2"
          />
        )}

        {/* x ticks */}
        {tickIdx.map((i) => (
          <text
            key={i}
            x={x(i)}
            y={H - 6}
            textAnchor="middle"
            className="sb-axis"
          >
            {fmtWeek(weeks[i])}
          </text>
        ))}

        {/* RTC+B cutover marker */}
        {cutIdx > 0 && (
          <g>
            <line
              x1={x(cutIdx)}
              x2={x(cutIdx)}
              y1={M.t}
              y2={M.t + plotH}
              stroke="var(--text-secondary)"
              strokeWidth={1}
              strokeDasharray="3 3"
            />
            <text
              x={x(cutIdx) + 3}
              y={M.t + 9}
              className="sb-axis sb-axis--mark"
            >
              RTC+B
            </text>
          </g>
        )}

        {/* series lines */}
        {seriesVals.map((s) => (
          <path
            key={s.source}
            d={linePath(s.vals)}
            fill="none"
            stroke={s.color}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}

        {/* direct end-labels (secondary encoding for the CVD floor) */}
        {endLabels.map((e, k) => (
          <text
            key={k}
            x={M.l + plotW + 5}
            y={e.y + 3}
            className="sb-endlabel"
            fill={e.color}
          >
            {e.label}
          </text>
        ))}

        {/* hover guide + markers */}
        {hover != null && (
          <g>
            <line
              x1={x(hover)}
              x2={x(hover)}
              y1={M.t}
              y2={M.t + plotH}
              stroke="var(--border-bright)"
              strokeWidth={1}
            />
            {seriesVals.map((s) => {
              const v = s.vals[hover];
              return v == null ? null : (
                <circle
                  key={s.source}
                  cx={x(hover)}
                  cy={y(v)}
                  r={3.5}
                  fill={s.color}
                  stroke="var(--bg-panel)"
                  strokeWidth={1.5}
                />
              );
            })}
          </g>
        )}

        {/* hover capture */}
        <rect
          x={M.l}
          y={M.t}
          width={plotW}
          height={plotH}
          fill="transparent"
          onMouseMove={onMove}
          onMouseLeave={clearHover}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft") moveHover(-1);
            if (event.key === "ArrowRight") moveHover(1);
          }}
          tabIndex={0}
          aria-label="Use left and right arrow keys to inspect weekly values"
        />
      </svg>

      {hover != null && (
        <div
          className="sb-tip"
          style={{ left: Math.min(x(hover) + 8, width - 140), top: M.t }}
        >
          <div className="sb-tip__wk">{fmtWeek(weeks[hover])}</div>
          {seriesVals.map((s) => {
            const v = s.vals[hover];
            return (
              <div key={s.source} className="sb-tip__row">
                <span className="sb-tip__dot" style={{ background: s.color }} />
                <span className="sb-tip__lbl">{s.label}</span>
                <span className="sb-tip__val">
                  {v == null ? "—" : meta.fmt(v)}
                </span>
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
// The two served tracks. h1 is what the product actually published for D; h2 is
// the preview that fired a day earlier, before D's DAM auction cleared. They are
// never merged into one series — a preview and a final are differently-informed
// forecasts, so one board shows one track (api/scoreboard.py `_resolve_daily_horizon`).
const HORIZON_LABELS: Record<number, string> = {
  1: "Final · fires D−1",
  2: "Preview · fires D−2",
};

const LIVE_METRICS: { name: keyof DailyPoint; label: string }[] = [
  { name: "rank_spearman", label: "Rank ρ" },
  { name: "sign_agree", label: "Sign Agreement" },
  { name: "topdecile_hit", label: "Top-Decile Hit" },
  { name: "pooled_r2", label: "Pooled R²" },
];

function LiveGradePanel({
  daily,
  weekly,
  headlineWin,
  regime,
  onRegimeChange,
  onHorizonChange,
}: {
  daily: ScoreboardDaily;
  weekly: ScoreboardWeekly | null;
  headlineWin: HeadlineWindow | undefined;
  regime: string;
  onRegimeChange: (v: string) => void;
  onHorizonChange: (v: number) => void;
}) {
  // Delivery days present, most-recent first — the selector's options and default.
  const days = useMemo(
    () =>
      Array.from(new Set(daily.points.map((p) => p.delivery_date)))
        .sort()
        .reverse(),
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
  const val = (
    row: DailyPoint | undefined,
    name: keyof DailyPoint
  ): number | null => {
    const v = row ? (row[name] as number | null) : null;
    return v == null ? null : v;
  };

  return (
    <section className="sb-live">
      {/* Its own line, in the same `.sb-section-h` block every other section
          heading uses, so all four headings share one left edge; the controls
          sit on the row beneath rather than inline with the heading. */}
      <div className="sb-section-h label">Live · per-delivery-day grade</div>
      <div className="sb-live__head">
        {/* Which served track is being graded. Always labeled, even when only
            one track exists, so a number is never ambiguous about its vintage. */}
        {daily.horizons.length > 1 ? (
          <select
            className="sb-regime sb-live__day"
            value={daily.horizon}
            onChange={(e) => onHorizonChange(Number(e.target.value))}
            aria-label="Forecast track"
          >
            {daily.horizons.map((h) => (
              <option key={h} value={h}>
                {HORIZON_LABELS[h] ?? `Horizon ${h}`}
              </option>
            ))}
          </select>
        ) : (
          <span className="sb-live__ctx label">
            {HORIZON_LABELS[daily.horizon] ?? `Horizon ${daily.horizon}`}
          </span>
        )}
        <select
          className="sb-regime sb-live__day"
          value={selected}
          onChange={(e) => setDay(e.target.value)}
          aria-label="Delivery day"
        >
          {days.map((d) => (
            <option key={d} value={d}>
              {fmtDay(d)}
            </option>
          ))}
        </select>
        <div className="sb-live__meta">
          <span className="sb-live__ctx label">
            {model?.n_nodes != null ? `${model.n_nodes} nodes` : ""}
          </span>
          <span className="sb-meta sb-meta--sub">
            <span className="sb-meta__label label">
              <Term def="The model run whose backtest is scored on this page.">
                Backtest run
              </Term>
            </span>
            <span className="sb-meta__val">{weekly ? weekly.run_id : "—"}</span>
          </span>
          {headlineWin && (
            <span className="sb-meta sb-meta--sub">
              <span className="sb-meta__label label">
                <Term def="The rolling look-back the headline tiles average over — the length of backtest history scored on this page.">
                  Window
                </Term>
              </span>
              <span className="sb-meta__val">{headlineWin.window_days} days</span>
            </span>
          )}
          <span className="sb-meta sb-meta--sub">
            <span className="sb-meta__label label">
              <Term
                def={
                  <>
                    <span className="sb-pop-p">
                      Filters the whole board to a slice of hours by{" "}
                      <b>net load</b> — the demand that dispatchable (thermal +
                      battery) units must actually serve, and the main driver of
                      congestion.
                    </span>
                    <span className="sb-pop-p">
                      Hours are split into five equal buckets (quintiles) by net
                      load:
                    </span>
                    <span className="sb-pop-li">
                      <b>Net load</b> = demand − wind − solar.
                    </span>
                    <span className="sb-pop-li">
                      <b>Q1</b> — lowest net load; a slack, low-risk grid.
                    </span>
                    <span className="sb-pop-li">
                      <b>Q2–Q4</b> — the middle range.
                    </span>
                    <span className="sb-pop-li">
                      <b>Q5</b> — peak net load; the tightest, highest-risk hours.
                    </span>
                    <span className="sb-pop-p">
                      <b>All hours</b> pools every hour together.
                    </span>
                  </>
                }
              >
                Net-load Bucket
              </Term>
            </span>
            {headlineWin && (
              <Tooltip
                className="sb-meta__val"
                tip="Graded weeks in the current selection — changes with the Hours filter."
              >
                {headlineWin.weeks} wk
              </Tooltip>
            )}
            <select
              className="sb-regime"
              value={regime}
              onChange={(e) => onRegimeChange(e.target.value)}
            >
              {REGIMES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </span>
        </div>
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
              <div className="sb-tile__model">
                {m == null ? "—" : m.toFixed(2)}
              </div>
              <div className="sb-tile__cmp">
                {good != null && (
                  <span className="sb-delta" data-good={good}>
                    {good ? "▲" : "▼"} vs persist{" "}
                    {p == null ? "—" : p.toFixed(2)}
                  </span>
                )}
                <span className="sb-ceiling">
                  ceiling {o == null ? "—" : o.toFixed(2)}
                </span>
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
  const win =
    headline?.windows.find((w) => w.window_days === 90) ?? headline?.windows[0];
  if (!win) return null;
  const pick = (name: string) =>
    win.currencies.find((c) => c.currency === name);
  const tiles = [
    { name: "rank_spearman", label: "Rank ρ" },
    { name: "sign_agree", label: "Sign Agreement" },
    { name: "topdecile_hit", label: "Top-Decile Hit" },
  ];
  return (
    <div className="sb-tiles">
      {tiles.map((t) => {
        const c = pick(t.name);
        if (!c) return null;
        const good =
          c.persistence_delta == null
            ? null
            : c.higher_is_better
            ? c.persistence_delta >= 0
            : c.persistence_delta <= 0;
        return (
          <div key={t.name} className="sb-tile">
            <div className="label">{t.label}</div>
            <div className="sb-tile__model">
              {c.model == null ? "—" : c.model.toFixed(2)}
            </div>
            <div className="sb-tile__cmp">
              {good != null && (
                <span className="sb-delta" data-good={good}>
                  {good ? "▲" : "▼"} vs persist{" "}
                  {c.persistence == null ? "—" : c.persistence.toFixed(2)}
                </span>
              )}
              <span className="sb-ceiling">
                ceiling {c.oracle == null ? "—" : c.oracle.toFixed(2)}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── pooled pre/post-RTC+B split table ───────────────────────────────────────
function SplitTable({
  weekly,
  metric,
}: {
  weekly: ScoreboardWeekly;
  metric: MetricKey;
}) {
  const meta = METRICS[metric];
  const val = (label: string, source: string): number | null => {
    const sp = weekly.splits
      .find((s) => s.label === label)
      ?.sources.find((x) => x.source === source);
    const v = sp ? (sp[metric] as number | null) : null;
    return v == null ? null : v;
  };
  return (
    <div className="sb-splits">
      <div className="sb-split-grid">
        <span className="sb-h" />
        {SERIES.map((s) => (
          <span key={s.source} className="sb-h" style={{ color: s.color }}>
            {s.label}
          </span>
        ))}

        {weekly.splits.map((sp) => {
          const m = val(sp.label, "model");
          const p = val(sp.label, "persistence");
          const modelLeads =
            m != null && p != null && m !== p && (meta.higher ? m > p : m < p);
          const persistLeads = m != null && p != null && m !== p && !modelLeads;
          return (
            <div
              key={sp.label}
              className="sb-split-row"
              style={{ display: "contents" }}
            >
              <span className="sb-cat label">
                {SPLIT_LABELS[sp.label] ?? sp.label} · {sp.n_weeks}w
              </span>
              <span className="sb-v" data-lead={modelLeads}>
                {m == null ? "—" : meta.fmt(m)}
              </span>
              <span className="sb-v" data-lead={persistLeads}>
                {p == null ? "—" : meta.fmt(p)}
              </span>
              <span className="sb-v">
                {(() => {
                  const v = val(sp.label, "climatology");
                  return v == null ? "—" : meta.fmt(v);
                })()}
              </span>
              <span className="sb-v sb-v--ceiling">
                {(() => {
                  const v = val(sp.label, "oracle");
                  return v == null ? "—" : meta.fmt(v);
                })()}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// Inline defined-term: a dotted-underlined word whose definition rides the
// shared app-wide Tooltip (components/ui/Tooltip). `.sb-term` supplies only the
// underline affordance now; the popover surface, positioning, portal, and
// hover/focus behavior all come from Tooltip — so a defined term reads as the
// same tooltip system as every other hint. Opens below (placement="bottom"), as
// it always did, to stay clear of the rail's top scroll edge.
function Term({
  children,
  def,
}: {
  children: React.ReactNode;
  def: React.ReactNode;
}) {
  return (
    <Tooltip as="span" className="sb-term" placement="bottom" tip={def}>
      {children}
    </Tooltip>
  );
}

// ── right-rail glossary: plain-language notes on the sources and metrics ─────
// Laymen's read of what each line and each column means. Sits beside the board
// so a figure never has to be decoded from memory.
function Glossary() {
  return (
    <aside className="sb-guide">
      <div className="sb-guide__block">
        <div className="sb-guide__h">What the model predicts</div>
        <p className="sb-guide__p">
          A node's congestion price is a linear combination of every binding
          constraint's shadow price, weighted by that node's shift factor to
          each constraint:
        </p>
        <p className="sb-guide__eq">congestion = −Σ SF · μ</p>
        <p className="sb-guide__where">
          <b>μ:</b> a constraint's shadow price (≥ 0) — its $/MWh cost when{" "}
          <Term def="A constraint binds when its transmission line hits a physical limit; at that instant its shadow price μ rises above $0.">
            binding
          </Term>
          .
        </p>
        <p className="sb-guide__where">
          <b>SF:</b> the shift factor — the node's marginal sensitivity to that
          constraint. Recovered offline by ridge regression on the price
          identity, then treated as known — so the model only forecasts μ.
        </p>
        <p className="sb-guide__p">
          <Term def="A constraint binds when its transmission line hits a physical limit; at that instant its shadow price μ rises above $0.">
            Binding
          </Term>{" "}
          is rare (~3% of hours), so μ is split into two{" "}
          <Term def="A 'head' is one sub-model output. The forecast trains two and multiplies them together.">
            heads
          </Term>
          , multiplied:
        </p>
        <p className="sb-guide__eq">E[μ] = P(bind) · E[μ | bind]</p>
        <dl className="sb-guide__dl">
          <dt>Head 1: P(bind)</dt>
          <dd>
            Probability of binding: the chance the constraint binds this hour.
            Fit with a gradient-boosted classifier.
          </dd>
          <dt>Head 2: E[μ | bind]</dt>
          <dd>
            Expected shadow price given binding: how severe μ is when it does.
            Fit with a gradient-boosted regressor on log(μ), over binding hours
            only.
          </dd>
        </dl>
        <p className="sb-guide__p">
          Splitting matters: a single head (“regressor”) over all hours would
          just learn to say “about zero” — right on average, useless when it
          counts.
        </p>
        <p className="sb-guide__eg">
          <b>Example.</b> At 5pm the model sees a 10% chance a line binds —
          P(bind) = 0.10, Head&nbsp;1 — and a $200 shadow price if it does — E[μ
          | bind] = $200, Head&nbsp;2. Multiply: E[μ] = 0.10 × $200 = $20. A
          node with SF = −0.3 to that line then carries −SF · μ = −(−0.3) × $20
          = +$6 of congestion.
        </p>
      </div>

      <div className="sb-guide__block">
        <div className="sb-guide__h">Model Comparison Graph</div>
        <dl className="sb-guide__dl">
          <dt>Model</dt>
          <dd>Our forecast. Predicts congestion.</dd>
          <dt>Persistence</dt>
          <dd>
            Naïve baseline: tomorrow repeats yesterday. Each node's congestion
            is set to its actual value at the same hour on the prior day.
          </dd>
          <dt>Climatology</dt>
          <dd>
            Historical-average baseline, computed per hour-of-day: how often a
            node has congested at this hour × its typical severity when it does.
            No day-to-day signal — just the long-run norm. Example: a node that
            binds at 8pm on 6 of the past 100 days, averaging $150 when it does,
            gets an 8pm climatology of 0.06 × $150 ≈ $9.
          </dd>
          <dt>Oracle</dt>
          <dd>
            If you already knew the answer: the score you'd get ranking nodes by
            their realized congestion. A ceiling to measure against, not a
            rival.
          </dd>
        </dl>
      </div>

      <div className="sb-guide__block">
        <div className="sb-guide__h">Pre / Post-RTC+B</div>
        <p className="sb-guide__p">
          RTC+B was ERCOT's real-time co-optimization + batteries market change
          on 2025-12-11. We split the weeks there to check if the model's edge
          held through the redesign.
        </p>
      </div>

      <div className="sb-guide__block">
        <div className="sb-guide__h">
          Scoring: does it rank the right nodes?
        </div>
        <dl className="sb-guide__dl">
          <dt>Top-Decile Hit</dt>
          <dd>
            Of the nodes we predict in the worst 10%, the fraction that were
            actually in the realized worst 10%. 1 = every flagged node truly
            belonged there; ~0.1 = chance.
          </dd>
          <dt>Rank ρ (Spearman)</dt>
          <dd>
            How well the predicted ordering of nodes matches the actual order. 1
            = identical, 0 = unrelated.
          </dd>
          <dt>Sign Agreement</dt>
          <dd>
            How often the direction is right (import vs export). 0.5 = coin
            flip.
          </dd>
        </dl>
      </div>

      <div className="sb-guide__block">
        <div className="sb-guide__h">
          Magnitude: how close are the numbers to ERCOT historic?
        </div>
        <dl className="sb-guide__dl">
          <dt>
            <Term def="Scored over every node×hour cell together in one bucket, not computed per node and averaged.">
              Pooled
            </Term>{" "}
            R²
          </dt>
          <dd>
            Share of the real variation the forecast explains. 1 = perfect, 0 =
            no better than the average, below 0 = worse.
          </dd>
          <dt>MAE (Mean Absolute Error)</dt>
          <dd>
            The average gap between forecast and actual, in $/MWh. Typical miss;
            lower is better.
          </dd>
        </dl>
      </div>
    </aside>
  );
}

export default function ScoreboardPage() {
  const [regime, setRegime] = useState("all");
  // null = let the server pick the final track; a number is an explicit switch.
  const [horizon, setHorizon] = useState<number | null>(null);
  const [controls, dispatchControls] = useScoreboardControls();
  const {
    weekly, headline, daily, backtestLoading, liveLoading, liveError,
    connectionState, lastUpdated,
  } =
    useScoreboard(regime, horizon);

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
        <HeaderStatus connectionState={connectionState} lastUpdated={lastUpdated} />
      </header>

      <div className="sb-body">
        <main className="sb-main">
          {/* The live half — rendered independently of the backtest board, and
          gracefully absent until a served day has been graded (§0004). */}
          {daily && (
            <LiveGradePanel
              daily={daily}
              weekly={weekly}
              headlineWin={headlineWin}
              regime={regime}
              onRegimeChange={setRegime}
              onHorizonChange={setHorizon}
            />
          )}
          {!liveLoading && liveError && (
            <div className="sb-empty label">live grades could not be loaded.</div>
          )}

          {backtestLoading && <div className="sb-empty label">loading…</div>}
          {!backtestLoading && !weekly && (
            <div className="sb-empty label">
              no board loaded for “{regime}”.
            </div>
          )}

          {weekly && (
            <>
              {/* Every block on this page is a different measurement, and they
                  were previously distinguishable only by shape. Label each one
                  with what it measures and over what span: the live panel above
                  grades one served day, these tiles pool a rolling window of the
                  backtest, the chart is that backtest week by week, and the table
                  pools the whole walk. */}
              <div className="sb-section-h label">
                Backtest · rolling{" "}
                {headlineWin ? `${headlineWin.window_days}-day` : ""} headline
              </div>
              <HeadlineTiles headline={headline} />

              {/* metric controls: screening leads, magnitude behind a toggle */}
              <ScoreboardControls state={controls} dispatch={dispatchControls} />

              <div className="sb-section-h label">
                Backtest · weekly series ({METRICS[controls.metric].label})
              </div>
              <SeriesChart
                points={weekly.points}
                metric={controls.metric}
                cutover={weekly.rtc_b_cutover}
              />

              {/* legend — identity for ≥2 series, alongside the direct end-labels */}
              <div className="sb-legend">
                {SERIES.map((s) => (
                  <span key={s.source} className="sb-legend__item">
                    <i
                      className="sb-legend__swatch"
                      style={{ background: s.color }}
                    />{" "}
                    {s.label}
                  </span>
                ))}
              </div>

              <div className="sb-section-h label">
                Backtest · pooled over all weeks, split pre/post-RTC+B (
                {METRICS[controls.metric].label})
              </div>
              <SplitTable weekly={weekly} metric={controls.metric} />
            </>
          )}
        </main>
        <Glossary />
      </div>

      <style>{`
        .sb-page {
          height: 100%;
          /* Flex column: sticky-ish header on top, the two-pane body owns the
             rest and each pane scrolls on its own (graph static, notes scroll). */
          display: flex;
          flex-direction: column;
          overflow: hidden;
          background: var(--bg-base);
          color: var(--text-primary);
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

        /* board (left) + glossary rail (right). Same proportional split as the
           map: content flex:5, rail flex:2 → rail is ~2/7 of the width, floored
           at --panel-w so it never collapses too narrow. */
        .sb-body { flex: 1; min-height: 0; display: flex; align-items: stretch; gap: 0; }
        /* Each pane scrolls independently, so the graph stays put while the
           explanation is scrolled (and vice versa). */
        .sb-main { flex: 5 1 0; min-width: 0; overflow-y: auto; padding-bottom: 40px; }
        .sb-guide {
          flex: 2 1 0; min-width: var(--panel-w);
          overflow-y: auto;
          border-left: 1px solid var(--border);
          padding: 14px 16px 24px;
        }
        /* Blocks read as sections now: a rule + spacing separates each. */
        .sb-guide__block + .sb-guide__block {
          margin-top: 18px; padding-top: 18px;
          border-top: 1px solid var(--border);
        }
        .sb-guide__h {
          display: block; margin: 0 0 10px;
          font-size: 16px; font-weight: 600; line-height: 1.25;
          letter-spacing: normal; text-transform: none;
          color: var(--text-primary);
        }
        .sb-guide__p { font-size: 13.5px; line-height: 1.5; color: var(--text-secondary); margin: 0; }
        .sb-guide__p + .sb-guide__p, .sb-guide__dl + .sb-guide__p { margin-top: 8px; }
        .sb-guide__eq {
          font-family: var(--font-mono);
          font-size: 14px; color: var(--text-primary);
          text-align: center; margin: 8px 0;
          padding: 6px 8px; background: var(--bg-surface);
          border: 1px solid var(--border); border-radius: 3px;
        }
        .sb-guide__dl { margin: 0; }
        .sb-guide__dl dt { font-size: 13.5px; font-weight: 700; color: var(--text-primary); margin-top: 8px; }
        .sb-guide__dl dt:first-child { margin-top: 0; }
        .sb-guide__dl dd { margin: 1px 0 0; font-size: 13.5px; line-height: 1.5; color: var(--text-secondary); }

        /* "where:" lines under the congestion equation — μ: / SF: inline. */
        .sb-guide__where { margin: 6px 0 0; font-size: 13.5px; line-height: 1.5; color: var(--text-secondary); }
        .sb-guide__where + .sb-guide__where { margin-top: 4px; }
        .sb-guide__where b { color: var(--text-primary); font-family: var(--font-mono); }

        /* concrete worked example */
        .sb-guide__eg {
          margin-top: 10px; padding: 8px 10px;
          font-size: 13.5px; line-height: 1.5; color: var(--text-secondary);
          background: var(--bg-surface); border-radius: 3px;
          border-left: 2px solid var(--border-bright);
        }

        /* Inline defined term: just the underline affordance — the popover
           surface + behavior come from the shared Tooltip (.tt in index.css). */
        .sb-term {
          text-decoration: underline dotted; text-underline-offset: 2px;
          cursor: help; outline: none;
        }
        /* Only the first .sb-meta carries margin-left:auto; the Window / Hours
           groups sit alongside it, spaced by the topbar's own gap. */
        .sb-meta--sub { margin-left: 0; align-items: center; }
        .sb-meta--sub .sb-regime { margin-left: 6px; }

        /* Rich tooltip content (rendered inside .tt): paragraphs + a bulleted
           list. Unscoped so it styles the Net-load def portaled onto <body>. */
        .sb-pop-p { display: block; }
        .sb-pop-p + .sb-pop-p,
        .sb-pop-p + .sb-pop-li,
        .sb-pop-li + .sb-pop-p { margin-top: 7px; }
        .sb-pop-li {
          display: block; position: relative;
          padding-left: 13px; margin-top: 3px;
        }
        .sb-pop-li::before {
          content: "•"; position: absolute; left: 2px;
          color: var(--text-muted);
        }
        @media (max-width: 900px) {
          /* Stacked: independent-pane scrolling no longer applies — let the
             whole page scroll as one column again. */
          .sb-page { overflow-y: auto; }
          .sb-body { flex-direction: column; min-height: 0; }
          .sb-main { overflow: visible; padding-bottom: 0; }
          .sb-guide {
            flex-basis: auto; width: 100%; min-width: 0; overflow: visible;
            border-left: none; border-top: 1px solid var(--border);
          }
        }

        .sb-live { border-bottom: 1px solid var(--border); padding-bottom: 10px; }
        .sb-live__head { display: flex; align-items: center; gap: 12px; padding: 0 16px; flex-wrap: wrap; }
        .sb-live__day { margin-left: 0; }
        /* Nodes count + the model-run meta cluster, bunched at the right edge —
           the trailing counterpart to the topbar's own auto-margin convention. */
        .sb-live__meta { margin-left: auto; display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
        .sb-live__ctx { color: var(--text-muted); }

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
          /* Theme-aware surface (was a hardcoded dark rgba that ignored the
             light-mode toggle). */
          background: var(--bg-glass); border: 1px solid var(--border-bright);
          border-radius: 3px; padding: 6px 9px; font-size: 14px; min-width: 124px;
        }
        .sb-tip__wk { color: var(--accent); margin-bottom: 3px; font-size: 14px; }
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
