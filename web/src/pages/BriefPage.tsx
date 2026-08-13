import { useEffect, useMemo, useRef, useState } from "react";
import { addDays, format } from "date-fns";
import { Link } from "react-router-dom";
import type { AnalysisGrade, AnalysisGradeHalf, AnalysisGradeSupport, BriefHero, HeroSegment } from "../api/types";
import { fetchAnalysisBriefLatest, fetchAnalysisGrade, fetchBriefHero } from "../api/client";
import HeaderNav from "../components/layout/HeaderNav";
import DateRangePicker from "../components/playback/DateRangePicker";
import { CURATED_EVENTS } from "../lib/events";
import { ctInputToUtc, formatCT } from "../lib/time";
import { useTimeCursor } from "../hooks/useTimeCursor";

const fmtDay = (day: string) =>
  new Date(`${day}T12:00:00Z`).toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "America/Chicago",
  });

function Segments({ segments }: { segments: HeroSegment[] }) {
  return <>{segments.map((segment, i) => <span key={`${segment.ref}-${i}`}>{segment.text}</span>)}</>;
}

function Stage({ title, detail }: { title: string; detail: string }) {
  return (
    <section className="an-stage">
      <h2>{title}</h2>
      <p>{detail}</p>
    </section>
  );
}

function Fact({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="an-fact">
      <span className="an-fact__label">{label}</span>
      <strong className="an-fact__value">{value}</strong>
      <span className="an-fact__detail">{detail}</span>
    </div>
  );
}

const score = (value: number | null | undefined) => value == null ? "—" : `${value.toFixed(2)}`;
const percent = (value: number | null | undefined) => value == null ? "—" : `${Math.round(value * 100)}%`;
const multiple = (value: number | null | undefined) => value == null ? "—" : `${value.toFixed(2)}×`;
const scorePosition = (value: number | null | undefined) => `${Math.max(0, Math.min(100, (value ?? 0) * 100))}%`;
const beats = (model: number | null | undefined, comparator: number | null | undefined) => model != null && comparator != null && model >= comparator;

function ScoreWhisker({ model, persistence }: { model: number | null | undefined; persistence: number | null | undefined }) {
  if (model == null && persistence == null) return null;
  return (
    <div className="an-grade-card__whisker" aria-label={`Model ${score(model)}; persistence ${score(persistence)}`}>
      <span className="an-grade-card__whisker-line" />
      <i className="an-grade-card__whisker-model" style={{ left: scorePosition(model) }} />
      {persistence != null && <i className="an-grade-card__whisker-persistence" style={{ left: scorePosition(persistence) }} />}
      <div><span>0%</span><span>100%</span></div>
    </div>
  );
}

function GradeCard({
  kind,
  question,
  detail,
  model,
  modelHourly,
  persistence,
  support,
  entity,
  footer,
  formula,
  supportRows,
}: {
  kind: string;
  question: string;
  detail: string;
  model: number | null | undefined;
  modelHourly?: number | null | undefined;
  persistence: number | null | undefined;
  support: AnalysisGradeSupport | null | undefined;
  entity: string;
  footer: string;
  formula: string;
  supportRows: Array<{ value: string; label: string; win?: boolean }>;
}) {
  const [formulaOpen, setFormulaOpen] = useState(false);
  const formulaRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!formulaOpen) return;
    const closeIfOutside = (event: MouseEvent) => {
      if (!formulaRef.current?.contains(event.target as Node)) setFormulaOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setFormulaOpen(false);
    };
    document.addEventListener("mousedown", closeIfOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeIfOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [formulaOpen]);
  return (
    <article className={`an-grade-card an-grade-card--${kind.toLowerCase()}`}>
      <span className="an-grade-card__kind">{kind}</span>
      <h4>{question}</h4>
      <p className="an-grade-card__detail">{detail}</p>
      <div className="an-grade-card__value">
        <strong>{score(model)}</strong>
        {modelHourly !== undefined ? <><small>day</small><span>→</span><strong>{score(modelHourly)}</strong><small>hourly</small></> : <small>model</small>}
      </div>
      <ScoreWhisker model={model} persistence={persistence} />
      <div className="an-grade-card__support">
        {supportRows.map((row) => <div key={row.label} className={row.win ? "an-grade-card__comparison an-grade-card__comparison--win" : "an-grade-card__comparison"}>
          <strong>{row.value}</strong><span>{row.label}</span>
        </div>)}
      </div>
      <p className="an-grade-card__evidence">{footer}</p>
      <p className="an-grade-card__footer">{support
        ? entity === "node"
          ? `${support.daily_bound_count.toLocaleString()} node-days above the numerical-noise floor · ${support.hourly_bound_count.toLocaleString()} node-hours above it`
          : `${support.daily_bound_count.toLocaleString()} constraint-days that bind · ${support.hourly_bound_count.toLocaleString()} constraint-hours that bind`
        : "Supporting population unavailable"}</p>
      <div ref={formulaRef} className="an-grade-card__formula">
        <button type="button" aria-expanded={formulaOpen} onClick={() => setFormulaOpen((open) => !open)}>
          How it is calculated
        </button>
        {formulaOpen && <div className="an-grade-card__formula-popover" role="note">
          <pre>{formula}</pre>
        </div>}
      </div>
    </article>
  );
}

function GradeHalf({ label, half }: { label: string; half: AnalysisGradeHalf | undefined }) {
  if (!half?.graded) {
    return (
      <div className="an-grade__half an-grade__half--ungraded">
        <h3>{label}</h3>
        <p>Not graded{half?.unavailable_reason ? ` · ${half.unavailable_reason.replaceAll("_", " ")}` : ""}</p>
      </div>
    );
  }
  const nodes = label === "Nodes";
  const dailyRank = nodes ? half.model?.top_decile_daily_capture : half.model?.detection_ap;
  const persistenceDailyRank = nodes ? half.persistence?.top_decile_daily_capture : half.persistence?.detection_ap;
  const hourlyRank = nodes ? half.model?.top_decile_hourly_capture : half.model?.timing_hourly_skill;
  return (
    <div className="an-grade__half">
      <h3>{label}{half.universe_size != null && <span>{half.universe_size} scored</span>}</h3>
      <div className="an-grade__cards">
        <GradeCard
          kind="Detection"
          question={nodes ? "Did we identify the highest-congestion nodes?" : "Did we name the right elements?"}
          detail={nodes ? "Overlap of the forecast and settled top 10% of the complete absolute-congestion ranking." : "Ranks the full scored universe by forecast and rewards realized events near the top."}
          model={dailyRank}
          persistence={persistenceDailyRank}
          support={half.support}
          entity={nodes ? "node" : "constraint"}
          supportRows={[
            { value: score(persistenceDailyRank), label: "Persistence (repeat yesterday)", win: beats(dailyRank, persistenceDailyRank) },
            { value: score(nodes ? half.climatology?.top_decile_daily_capture : half.climatology?.detection_ap), label: "30-day settled average", win: beats(dailyRank, nodes ? half.climatology?.top_decile_daily_capture : half.climatology?.detection_ap) },
            { value: percent(nodes ? 0.10 : half.support?.daily_bound_rate), label: nodes ? "Random top-decile capture" : "Blind guess" },
          ]}
          footer={half.support ? (nodes ? `Top ${Math.ceil((half.universe_size ?? 0) * 0.1).toLocaleString()} of ${half.universe_size?.toLocaleString() ?? "—"} nodes · 10% random capture is the baseline.` : `${half.support.daily_bound_count.toLocaleString()} bound of ${half.universe_size?.toLocaleString() ?? "—"} constraints · 100% means every realized event ranked first.`) : "Measures average precision."}
          formula={nodes
            ? `Capture₁₀ = | Top₁₀%(forecast) ∩ Top₁₀%(settled) |
            ───────────────────────────────────────────────
                         ceil(0.10 × N)

N = complete, unfiltered node universe`
            : `AP  =  (1/B) · Σ  P(k)
                         k ∈ bound

P(k) = bound within top k ÷ k
B    = constraints that bind`}
        />
        <GradeCard
          kind="Magnitude"
          question="Were the prices about right?"
          detail="Matches forecast dollars to settled dollars by element. A forecast with the wrong total cannot reach 1.00, even with perfect placement."
          model={half.model?.magnitude_overlap}
          persistence={half.persistence?.magnitude_overlap}
          support={half.support}
          entity={label === "Constraints" ? "constraint" : "node"}
          supportRows={[
            { value: multiple(half.support?.forecast_to_settled_ratio), label: "Forecast dollars per settled dollar" },
            { value: score(half.support?.magnitude_ceiling), label: "Highest overlap possible with this total" },
            { value: percent(half.support?.magnitude_of_ceiling), label: "Share of that maximum achieved" },
          ]}
          footer={half.support ? `${usd(half.support.forecast_total)} forecast · ${usd(half.support.settled_total)} settled.` : "Measures soft overlap of daily magnitude."}
          formula={`2 × Σ min(forecastᵢ, settledᵢ)
────────────────────────────────
    Σ forecastᵢ  +  Σ settledᵢ`}
        />
        <GradeCard
          kind="Timing"
          question={nodes ? "Did the same high-congestion nodes appear in the right hours?" : "Did the right signal arrive in the right hours?"}
          detail={nodes ? "The 0.xx scores are settled top-decile nodes captured by the forecast; the 10% lines below are random-selection baselines." : "Shows the delivery-day result beside the same test over individual hours."}
          model={nodes ? dailyRank : half.model?.timing_daily_skill}
          modelHourly={hourlyRank}
          persistence={nodes ? persistenceDailyRank : half.persistence?.timing_daily_skill}
          support={half.support}
          entity={nodes ? "node" : "constraint"}
          supportRows={[
            { value: percent(nodes ? 0.10 : half.support?.daily_bound_rate), label: nodes ? "Random daily capture baseline" : "Constraint-days that bind" },
            { value: percent(nodes ? 0.10 : half.support?.hourly_bound_rate), label: nodes ? "Random hourly capture baseline" : "Constraint-hours that bind" },
          ]}
          footer={nodes ? "Daily capture first, then capture averaged across delivery hours; each comparison selects 10% of nodes." : "Daily score first, then the same chance-adjusted ranking test over all delivery hours."}
          formula={nodes
            ? `Hourly capture₁₀ = (1/H) · Σ  | Top₁₀%(forecastₕ) ∩ Top₁₀%(settledₕ) |
                                  h                 ────────────────────────────────────
                                                   ceil(0.10 × N)

N = complete node universe · H = delivery hours`
            : `(AP − chance) ÷ (1 − chance)
run on days, then on hours

chance = share that bind`}
        />
      </div>
    </div>
  );
}

function ForecastGrade({ grade, loading }: { grade: AnalysisGrade | null; loading: boolean }) {
  return (
    <section className="an-grade" aria-labelledby="forecast-grade-title">
      <h2 id="forecast-grade-title">Forecast Grade</h2>
      {loading && <p>Loading forecast grade…</p>}
      {!loading && (!grade || !grade.available) && <p>Forecast grade is unavailable for this delivery day.</p>}
      {!loading && grade?.available && <div className="an-grade__halves">
        <GradeHalf label="Constraints" half={grade.constraints} />
        <GradeHalf label="Nodes" half={grade.nodes} />
      </div>}
    </section>
  );
}

const numeric = (slot: Record<string, unknown> | undefined, key: string) => {
  const value = slot?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
};

const usd = (value: number) => `${value < 0 ? "−" : ""}$${Math.abs(value).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
const pct = (value: number) => `${Math.round(value * 100)}%`;

function dateBounds(day: string) {
  const nextDay = format(addDays(new Date(`${day}T12:00:00Z`), 1), "yyyy-MM-dd");
  return {
    start: ctInputToUtc(`${day}T00:00`),
    end: ctInputToUtc(`${nextDay}T00:00`),
  };
}

// v6 is deliberately a separate composition from the legacy, precomputed
// Analysis page. It owns only a delivery day; the map/matrix playback session
// remains mounted exclusively on those surfaces.
export default function BriefPage() {
  const cursor = useTimeCursor();
  const cursorDay = cursor.t ? formatCT(cursor.t, "yyyy-MM-dd") : null;
  const [defaultDay, setDefaultDay] = useState<string | null>(null);
  const [indexLoaded, setIndexLoaded] = useState(false);
  const [hero, setHero] = useState<BriefHero | null>(null);
  const [grade, setGrade] = useState<AnalysisGrade | null>(null);
  const [loading, setLoading] = useState(false);
  const [gradeLoading, setGradeLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeEventId, setActiveEventId] = useState<string | null>(null);
  const [replaceWithHeroCursor, setReplaceWithHeroCursor] = useState(false);

  // Until the date picker lands, the legacy index is solely a discovery source
  // for the newest delivery day.  All Brief content comes from /analysis/hero.
  useEffect(() => {
    if (cursorDay) {
      setIndexLoaded(true);
      return;
    }
    let live = true;
    fetchAnalysisBriefLatest()
      .then((latest) => {
        if (!live) return;
        setDefaultDay(latest?.delivery_date ?? null);
        setIndexLoaded(true);
      })
      .catch(() => {
        if (live) setIndexLoaded(true);
      });
    return () => { live = false; };
  }, [cursorDay]);

  const deliveryDay = cursorDay ?? defaultDay;

  useEffect(() => {
    if (!deliveryDay) return;
    let live = true;
    setLoading(true);
    setError(null);
    fetchBriefHero(deliveryDay, cursor.run ?? undefined)
      .then((result) => {
        if (!live) return;
        setHero(result);
        setLoading(false);
      })
      .catch(() => {
        if (!live) return;
        setError("The daily brief could not be loaded.");
        setLoading(false);
      });
    return () => { live = false; };
  }, [deliveryDay, cursor.run]);

  useEffect(() => {
    if (!deliveryDay) return;
    let live = true;
    setGradeLoading(true);
    fetchAnalysisGrade(deliveryDay, { runId: cursor.run ?? undefined })
      .then((result) => { if (live) setGrade(result); })
      .catch(() => { if (live) setGrade(null); })
      .finally(() => { if (live) setGradeLoading(false); });
    return () => { live = false; };
  }, [deliveryDay, cursor.run]);

  // A cold visit has no coordinate.  The hero supplies an exact delivery-day
  // cursor; write all three fields so the first URL is immediately shareable.
  // Preserve a complete coordinate handed over by Map/Matrix, including its
  // wider load window.
  useEffect(() => {
    if (!hero?.available || !hero.cursor) return;
    if (!replaceWithHeroCursor && cursor.t && cursor.ws && cursor.we) return;
    cursor.setCoord({
      t: new Date(hero.cursor.t),
      ws: new Date(hero.cursor.ws),
      we: new Date(hero.cursor.we),
    }, { replace: true });
    setReplaceWithHeroCursor(false);
  }, [hero, cursor, replaceWithHeroCursor]);

  const provenance = hero?.provenance;
  const basisLabel = provenance?.basis === "settled" ? "DAM settled" : "forecast";
  const title = useMemo(
    () => hero?.segments?.headline ?? [],
    [hero]
  );
  const magnitude = hero?.slots?.magnitude;
  const where = hero?.slots?.where;
  const exceptions = hero?.slots?.exceptions;
  const magnitudeValue = numeric(magnitude, "value");
  const magnitudeRank = numeric(magnitude, "rank");
  const magnitudeN = numeric(magnitude, "n");
  const magnitudeMedian = numeric(magnitude, "med");
  const whereShare = numeric(where, "share");
  const whereZone = typeof where?.zone === "string" ? where.zone : null;
  const exceptionCount = numeric(exceptions, "count");
  const exceptionsSettled = exceptions?.available !== false;

  return (
    <div className="an-page">
      <header className="an-topbar">
        <HeaderNav active="brief" />
        {deliveryDay && <span className="an-day">{fmtDay(deliveryDay)}</span>}
        {provenance && <span className={`an-basis an-basis--${provenance.basis}`}>{basisLabel}</span>}
      </header>

      <main className="an-main">
        {indexLoaded && (
          <div className="an-date-picker">
            <DateRangePicker
              singleDate
              selectedDate={deliveryDay}
              onLoadDate={(day) => {
                const { start, end } = dateBounds(day);
                setActiveEventId(null);
                setReplaceWithHeroCursor(true);
                cursor.setCoord({ t: start, ws: start, we: end });
              }}
              onSelectEvent={(event) => {
                setActiveEventId(event.id);
                cursor.setCoord({
                  t: new Date(event.cursor_ts),
                  ws: new Date(event.window_start),
                  we: new Date(event.window_end),
                });
              }}
              events={CURATED_EVENTS}
              activeEventId={activeEventId}
              loading={loading}
            />
          </div>
        )}
        {!indexLoaded && <p className="an-empty">Loading brief…</p>}
        {indexLoaded && !deliveryDay && <p className="an-empty">No forecast delivery day is published yet.</p>}
        {loading && <p className="an-empty">Loading brief…</p>}
        {error && <p className="an-empty">{error}</p>}
        {!loading && hero && !hero.available && <p className="an-empty">No forecast artifact is available for {deliveryDay ? fmtDay(deliveryDay) : "this day"}.</p>}

        {!loading && hero?.available && hero.segments && (
          <>
            <section className="an-hero" aria-labelledby="brief-title">
              <p className="an-eyebrow">Daily congestion brief</p>
              <h1 id="brief-title"><Segments segments={title} /></h1>
              <p className="an-lede"><Segments segments={hero.segments.lede} /></p>
              <div className="an-facts" aria-label="Brief evidence">
                {magnitudeValue != null && (
                  <Fact
                    label="Congestion total"
                    value={usd(magnitudeValue)}
                    detail={provenance?.basis === "settled" ? "DAM shadow-price total" : "forecast shadow-price total"}
                  />
                )}
                {magnitudeRank != null && magnitudeN != null && (
                  <Fact
                    label="30-day rank"
                    value={`${magnitudeRank} of ${magnitudeN}`}
                    detail={magnitudeMedian != null ? `median ${usd(magnitudeMedian)}` : "including this delivery day"}
                  />
                )}
                {whereZone && whereShare != null && (
                  <Fact
                    label="Where it priced"
                    value={whereZone}
                    detail={`${pct(whereShare)} of μ-weighted footprint`}
                  />
                )}
                {exceptionsSettled && exceptionCount != null && (
                  <Fact
                    label="Outside forecast"
                    value={String(exceptionCount)}
                    detail="material DAM constraints outside the model vocabulary"
                  />
                )}
              </div>
              <div className="an-hero__meta">
                <span>Run {provenance?.run_id}</span>
                <span>{provenance?.horizon === 1 ? "final · t+1" : "preview · t+2"}</span>
                <Link to={`/map${window.location.search}`}>Open this day on the map →</Link>
              </div>
            </section>

            <Stage title="Standouts" detail="Unusual constraints and nodes will land with their query-backed rows." />
            <Stage title="Top Constraints by Shadow Price (μ)" detail="The untruncated constraint panel follows the query endpoint." />
            <Stage title="Top Nodal Congestion" detail="Nodal attribution will render from the full shift-factor column." />
            <ForecastGrade grade={grade} loading={gradeLoading} />
            <Stage title="Context" detail="Historical grid context will follow its dedicated rollups." />
          </>
        )}
      </main>

      <style>{`
        .an-page { height: 100%; overflow-y: auto; background: var(--bg-base); color: var(--text-primary); font-variant-numeric: tabular-nums; }
        .an-topbar { position: sticky; top: 0; z-index: 2; height: var(--header-h); padding: 0 16px; display: flex; align-items: center; gap: 12px; background: var(--bg-panel); border-bottom: 1px solid var(--border); }
        .an-day { margin-left: auto; font: var(--fw-label) var(--fs-md) var(--font-label); letter-spacing: var(--track-label); }
        .an-basis { padding: 3px 7px; border: 1px solid var(--border); border-radius: 3px; color: var(--text-secondary); font: var(--fw-label) var(--fs-xs) var(--font-label); letter-spacing: var(--track-label); text-transform: uppercase; }
        .an-basis--settled { color: var(--success, var(--accent)); }
        .an-main { width: min(960px, calc(100% - 32px)); margin: 0 auto; padding: 42px 0 80px; }
        .an-date-picker { display: flex; justify-content: flex-end; margin-bottom: 16px; }
        .an-hero { padding-bottom: 32px; border-bottom: 2px solid var(--text-primary); }
        .an-eyebrow { margin: 0 0 8px; color: var(--text-secondary); font: var(--fw-label) var(--fs-xs) var(--font-label); letter-spacing: var(--track-label); text-transform: uppercase; }
        .an-hero h1 { max-width: 28ch; margin: 0; font-size: clamp(28px, 4vw, 44px); line-height: 1.14; letter-spacing: -0.025em; }
        .an-lede { max-width: 72ch; margin: 16px 0 0; color: var(--text-secondary); font-size: var(--fs-lg); line-height: 1.55; }
        .an-facts { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; margin-top: 24px; border: 1px solid var(--border); background: var(--border); }
        .an-fact { min-width: 0; padding: 11px 12px; background: var(--bg-panel); }
        .an-fact__label, .an-fact__detail { display: block; color: var(--text-muted); font-size: var(--fs-label); line-height: 1.35; }
        .an-fact__value { display: block; overflow: hidden; margin: 4px 0 3px; color: var(--text-primary); font-family: var(--font-mono); font-size: var(--fs-lg); text-overflow: ellipsis; white-space: nowrap; }
        .an-hero__meta { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 20px; color: var(--text-secondary); font-size: var(--fs-sm); }
        .an-hero__meta a { color: var(--accent); text-decoration: none; }
        .an-hero__meta a:hover { text-decoration: underline; }
        .an-stage { margin-top: 42px; }
        .an-stage h2 { margin: 0; font-size: var(--fs-xl); }
        .an-stage p { margin: 7px 0 0; color: var(--text-secondary); }
        .an-grade { margin-top: 42px; }
        .an-grade h2 { margin: 0; font-size: var(--fs-xl); }
        .an-grade > p, .an-grade__half--ungraded p { margin: 7px 0 0; color: var(--text-secondary); }
        .an-grade__halves { display: grid; gap: 18px; margin-top: 12px; }
        .an-grade__half { min-width: 0; }
        .an-grade__half h3 { margin: 0 0 8px; font-size: var(--fs-md); }
        .an-grade__half h3 span { margin-left: 7px; color: var(--text-muted); font-size: var(--fs-label); font-weight: normal; }
        .an-grade__half--ungraded { padding: 14px; border: 1px dashed var(--border-bright); background: var(--bg-panel); }
        .an-grade__cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; border: 1px solid var(--border); background: var(--border); }
        .an-grade-card { position: relative; display: flex; min-width: 0; min-height: 282px; padding: 12px; background: var(--bg-panel); flex-direction: column; }
        .an-grade-card__kind { align-self: flex-start; padding: 2px 5px; color: var(--bg-base); font-family: var(--font-label); font-size: var(--fs-micro); font-weight: 700; letter-spacing: var(--track-title); text-transform: uppercase; }
        .an-grade-card--detection .an-grade-card__kind { background: var(--accent); }
        .an-grade-card--magnitude .an-grade-card__kind { background: var(--warn); }
        .an-grade-card--timing .an-grade-card__kind { background: var(--violet); }
        .an-grade-card h4 { margin: 5px 0 0; color: var(--text-primary); font-size: var(--fs-body); line-height: 1.35; }
        .an-grade-card__detail { min-height: 43px; margin: 4px 0 0; color: var(--text-secondary); font-size: var(--fs-label); line-height: 1.4; }
        .an-grade-card__value { display: flex; align-items: baseline; gap: 5px; min-height: 32px; margin: 7px 0 5px; color: var(--text-primary); font-family: var(--font-mono); }
        .an-grade-card__value strong { font-size: 22px; font-weight: 600; }
        .an-grade-card__value span { color: var(--text-muted); font-size: var(--fs-md); }
        .an-grade-card__value small { color: var(--text-muted); font-family: var(--font-sans); font-size: var(--fs-micro); }
        .an-grade-card__whisker { position: relative; height: 25px; margin: 0 0 5px; }
        .an-grade-card__whisker-line { position: absolute; top: 8px; right: 0; left: 0; height: 2px; background: var(--border-bright); }
        .an-grade-card__whisker i { position: absolute; top: 3px; width: 3px; height: 12px; transform: translateX(-50%); }
        .an-grade-card__whisker-model { background: var(--accent); }
        .an-grade-card__whisker-persistence { background: var(--text-muted); }
        .an-grade-card__whisker div { position: absolute; right: 0; bottom: 0; left: 0; display: flex; justify-content: space-between; color: var(--text-muted); font-size: var(--fs-micro); }
        .an-grade-card__support { margin-top: 2px; }
        .an-grade-card__comparison { display: flex; gap: 8px; align-items: baseline; min-height: 18px; color: var(--text-muted); font-size: var(--fs-micro); }
        .an-grade-card__comparison strong { min-width: 38px; color: var(--text-secondary); font-family: var(--font-mono); font-size: var(--fs-label); }
        .an-grade-card__comparison--win strong { color: var(--ok); }
        .an-grade-card__evidence { min-height: 28px; margin: 8px 0 0; color: var(--text-muted); font-size: var(--fs-micro); line-height: 1.35; }
        .an-grade-card__footer { min-height: 27px; margin: auto 0 0; padding-top: 8px; border-top: 1px solid var(--border); color: var(--text-muted); font-size: var(--fs-micro); line-height: 1.35; }
        .an-grade-card__formula { position: relative; margin-top: 6px; font-size: var(--fs-micro); }
        .an-grade-card__formula button { padding: 0; border: 0; background: transparent; color: var(--accent); font: inherit; cursor: pointer; }
        .an-grade-card__formula-popover { position: absolute; z-index: 2; bottom: calc(100% + 7px); left: 0; width: max-content; max-width: min(430px, calc(100vw - 48px)); padding: 10px; border: 1px solid var(--border-bright); background: var(--bg-panel); box-shadow: 0 8px 22px rgb(0 0 0 / 22%); }
        .an-grade-card__formula-popover pre { margin: 0; overflow-x: auto; color: var(--text-secondary); font-family: var(--font-mono); font-size: var(--fs-micro); line-height: 1.4; white-space: pre; }
        .an-empty { margin: 40px 0; color: var(--text-secondary); font-family: var(--font-label); }
        @media (max-width: 700px) { .an-facts { grid-template-columns: repeat(2, minmax(0, 1fr)); } .an-grade__cards { grid-template-columns: 1fr; } .an-grade-card { min-height: 0; } }
        @media (max-width: 640px) { .an-day { display: none; } .an-main { width: min(100% - 24px, 960px); padding-top: 28px; } }
      `}</style>
    </div>
  );
}
