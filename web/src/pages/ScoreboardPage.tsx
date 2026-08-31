import { useMemo } from "react";
import type {
  ScoreboardWeekly,
  ScoreboardHeadline,
  ScoreboardDaily,
  DailyPoint,
  ScoreHistoryPoint,
  SourceDescriptor,
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
// metric-vs-baselines-vs-oracle series, a coverage strip on the shared x-axis,
// and the pooled pre/post-RTC+B split. Reads scoreboard_weekly only —
// independent of the forecast run. Integrity (§6): a model figure never appears
// without persistence + oracle in frame.

// The four charted sources, in fixed identity order, colored from the dataviz
// reference palette's dark categorical slots 1–4 (validated on the panel
// surface). CVD sits at the permitted first-four floor, so the required
// secondary encoding ships too: a legend + direct end-labels on every line.
const SERIES = [
  { seriesId: "model", color: "#3987e5" },
  { seriesId: "persistence", color: "#008300" },
  { seriesId: "climatology", color: "#d55181" },
  { seriesId: "oracle", color: "#c98500" },
] as const;

const descriptorById = (sources: SourceDescriptor[]) =>
  new Map(sources.map((source) => [source.id, source]));


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

// ── the backtest + served-grade series chart (hand-rolled SVG) ──────────────
function SeriesChart({
  points,
  metric,
  cutover,
  boundaryDate,
  sources,
}: {
  points: ScoreHistoryPoint[];
  metric: MetricKey;
  cutover: string;
  boundaryDate: string | null;
  sources: SourceDescriptor[];
}) {
  const dates = useMemo(
    () => Array.from(new Set(points.map((p) => p.week ?? p.delivery_date ?? ""))).sort(),
    [points]
  );
  const byKey = useMemo(() => {
    const m = new Map<string, ScoreHistoryPoint>();
    for (const p of points) m.set(`${p.week ?? p.delivery_date}|${p.series_id}`, p);
    return m;
  }, [points]);

  const meta = METRICS[metric];
  const valueAt = (i: number, seriesId: string): number | null => {
    const p = byKey.get(`${dates[i]}|${seriesId}`);
    const v = p ? (p[metric] as number | null) : null;
    return v == null ? null : v;
  };

  const seriesVals = useMemo(
    () =>
      SERIES.map((s) => ({
        ...s,
        vals: dates.map((_, i) => valueAt(i, s.seriesId)),
      })),
    [dates, byKey, metric] // eslint-disable-line react-hooks/exhaustive-deps
  );

  const allVals = seriesVals.flatMap((s) =>
    s.vals.filter((v): v is number => v != null)
  );
  const [dMin, dMax] = meta.domain(allVals);

  // Right margin holds the direct end-labels (Persistence / Climatology ≈ 80px
  // at the 11px label face) — keep it wide enough that they don't clip.
  const M = { t: 14, r: 116, b: 22, l: 42 };
  const H = 280;
  const n = dates.length;
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
  const descriptors = descriptorById(sources);
  type EndLabel = { color: string; label: string; y: number };
  const endLabels: EndLabel[] = [];
  for (const s of seriesVals) {
    for (let i = s.vals.length - 1; i >= 0; i--) {
      const v = s.vals[i];
      if (v != null) {
        const point = byKey.get(`${dates[i]}|${s.seriesId}`);
        endLabels.push({ color: s.color, label: descriptors.get(point?.source_id ?? "")?.label ?? s.seriesId, y: y(v) });
        break;
      }
    }
  }
  endLabels.sort((a, b) => a.y - b.y);
  for (let i = 1; i < endLabels.length; i++) {
    if (endLabels[i].y - endLabels[i - 1].y < 12)
      endLabels[i].y = endLabels[i - 1].y + 12;
  }

  const cutIdx = dates.findIndex((d) => d >= cutover);
  const boundaryIdx = boundaryDate == null ? -1 : dates.findIndex((d) => d >= boundaryDate);
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
            {fmtWeek(dates[i])}
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

        {boundaryIdx > 0 && (
          <g>
            <line
              x1={x(boundaryIdx)}
              x2={x(boundaryIdx)}
              y1={M.t}
              y2={M.t + plotH}
              stroke="var(--accent)"
              strokeWidth={1}
              strokeDasharray="5 3"
            />
            <text x={x(boundaryIdx) + 3} y={M.t + 21} className="sb-axis sb-axis--mark">
              Served grades
            </text>
          </g>
        )}

        {/* series lines */}
        {seriesVals.map((s) => (
          <path
            key={s.seriesId}
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
                  key={s.seriesId}
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
          aria-label="Use left and right arrow keys to inspect backtest and served-grade values"
        />
      </svg>

      {hover != null && (
        <div
          className="sb-tip"
          style={{ left: Math.min(x(hover) + 8, width - 140), top: M.t }}
        >
          <div className="sb-tip__wk">
            {points.find((p) => (p.week ?? p.delivery_date) === dates[hover])?.cadence === "served_daily"
              ? `Served daily grade · ${fmtDay(dates[hover])}`
              : `Walk-forward backtest week · ${fmtWeek(dates[hover])}`}
          </div>
          {seriesVals.map((s) => {
            const v = s.vals[hover];
            return (
              <div key={s.seriesId} className="sb-tip__row">
                <span className="sb-tip__dot" style={{ background: s.color }} />
                <span className="sb-tip__lbl">{
                  descriptors.get(byKey.get(`${dates[hover]}|${s.seriesId}`)?.source_id ?? "")?.label ?? s.seriesId
                }</span>
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
// "How did the latest served forecast do." The server selects the newest final
// grade and its comparator rows; the chart below carries the historical series.

// The graded currencies foregrounded for the latest final day. All higher-is-better, so a
// positive model−persistence delta is the model winning (matches HeadlineTiles +
// the _CURRENCIES orientation the API pools on).
const LIVE_METRICS: { name: keyof DailyPoint; label: string }[] = [
  { name: "rank_spearman", label: "Rank ρ" },
  { name: "sign_agree", label: "Sign Agreement" },
  { name: "topdecile_hit", label: "Top-Decile Hit" },
];

function LiveGradePanel({
  daily,
}: {
  daily: ScoreboardDaily;
}) {
  const selected = daily.selected_delivery_date ?? daily.points[0]?.delivery_date;
  const bySource = useMemo(() => {
    const m = new Map<string, DailyPoint>();
    for (const p of daily.points) {
      if (p.delivery_date === selected) m.set(p.series_id, p);
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
      <div className="sb-section-h label">Live · latest final served grade</div>
      <div className="sb-live__head">
        <span className="sb-live__ctx label">
          Final served {selected ? fmtDay(selected) : "grade"}
        </span>
        <div className="sb-live__meta">
          <span className="sb-live__ctx label">
            {model?.n_nodes != null ? `${model.n_nodes} nodes` : ""}
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
                    {good ? "▲" : "▼"} vs prior-day nodal persistence{" "}
                    {p == null ? "—" : p.toFixed(2)}
                  </span>
                )}
                <span className="sb-ceiling">
                  settled-μ nodal ceiling {o == null ? "—" : o.toFixed(2)}
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
                  {good ? "▲" : "▼"} vs prior-day nodal persistence{" "}
                  {c.persistence == null ? "—" : c.persistence.toFixed(2)}
                </span>
              )}
              <span className="sb-ceiling">
                settled-μ nodal ceiling {c.oracle == null ? "—" : c.oracle.toFixed(2)}
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
      ?.sources.find((x) => x.series_id === source);
    const v = sp ? (sp[metric] as number | null) : null;
    return v == null ? null : v;
  };
  return (
    <div className="sb-splits">
      <div className="sb-split-grid">
        <span className="sb-h" />
        {SERIES.map((s) => (
          <span key={s.seriesId} className="sb-h" style={{ color: s.color }}>
            {weekly.sources.find((source) => source.series_id === s.seriesId)?.label ?? s.seriesId}
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
          <dt>Walk-forward nodal forecast</dt>
          <dd>The offline forecast construction, projected to nodal congestion.</dd>
          <dt>Prior-day nodal persistence</dt>
          <dd>
            Naïve baseline: tomorrow repeats yesterday. Each node's congestion
            is set to its actual value at the same hour on the prior day.
          </dd>
          <dt>Trailing-window nodal baseline</dt>
          <dd>
            Historical-average baseline, computed per hour-of-day: how often a
            node has congested at this hour × its typical severity when it does.
            No day-to-day signal — just the long-run norm. Example: a node that
            binds at 8pm on 6 of the past 100 days, averaging $150 when it does,
            gets an 8pm climatology of 0.06 × $150 ≈ $9.
          </dd>
          <dt>Settled-μ nodal ceiling</dt>
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

    </aside>
  );
}

export default function ScoreboardPage() {
  const [controls, dispatchControls] = useScoreboardControls();
  const {
    weekly, headline, daily, history, backtestLoading, liveLoading, liveError,
    connectionState, lastUpdated,
  } =
    useScoreboard();

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
            />
          )}
          {!liveLoading && liveError && (
            <div className="sb-empty label">live grades could not be loaded.</div>
          )}

          {backtestLoading && <div className="sb-empty label">loading…</div>}
          {!backtestLoading && !weekly && (
            <div className="sb-empty label">
              no board loaded.
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

              <ScoreboardControls state={controls} dispatch={dispatchControls} />

              <div className="sb-section-h label">
                Track record · weekly backtest and served daily grades ({METRICS[controls.metric].label})
              </div>
              {history ? (
                <SeriesChart
                  points={history.points}
                  metric={controls.metric}
                  cutover={weekly.rtc_b_cutover}
                  boundaryDate={history.boundary_date}
                  sources={history.sources}
                />
              ) : (
                <div className="sb-empty label">track history could not be loaded.</div>
              )}

              {/* legend — identity for ≥2 series, alongside the direct end-labels */}
              <div className="sb-legend">
                {SERIES.map((s) => (
                  <span key={s.seriesId} className="sb-legend__item">
                    <i
                      className="sb-legend__swatch"
                      style={{ background: s.color }}
                    />{" "}
                    {weekly.sources.find((source) => source.series_id === s.seriesId)?.label ?? s.seriesId}
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

    </div>
  );
}
