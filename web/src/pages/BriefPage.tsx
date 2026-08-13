import { useEffect, useMemo, useState } from "react";
import { addDays, format } from "date-fns";
import { Link } from "react-router-dom";
import type { AnalysisGrade, AnalysisGradeHalf, AnalysisGradeMetrics, BriefHero, HeroSegment } from "../api/types";
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

const score = (value: number | null | undefined) => value == null ? "—" : `${Math.round(value * 100)}%`;

function GradeMetricRow({ label, metrics }: { label: string; metrics: AnalysisGradeMetrics | null | undefined }) {
  return (
    <div className="an-grade__row">
      <span>{label}</span>
      <span>{score(metrics?.detection_ap)}</span>
      <span>{score(metrics?.magnitude_overlap)}</span>
      <span>{score(metrics?.timing_daily_skill)}</span>
      <span>{score(metrics?.timing_hourly_skill)}</span>
    </div>
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
  return (
    <div className="an-grade__half">
      <h3>{label}{half.universe_size != null && <span>{half.universe_size} scored</span>}</h3>
      <div className="an-grade__table" role="table" aria-label={`${label} forecast grade`}>
        <div className="an-grade__row an-grade__row--head" role="row">
          <span>Method</span><span>Detection</span><span>Magnitude</span><span>Daily timing</span><span>Hourly timing</span>
        </div>
        <GradeMetricRow label="Model" metrics={half.model} />
        <GradeMetricRow label="Persistence" metrics={half.persistence} />
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
        .an-page { min-height: 100%; background: var(--bg-base); color: var(--text-primary); font-variant-numeric: tabular-nums; }
        .an-topbar { height: var(--header-h); padding: 0 16px; display: flex; align-items: center; gap: 12px; background: var(--bg-panel); border-bottom: 1px solid var(--border); }
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
        .an-grade__halves { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin-top: 12px; }
        .an-grade__half { min-width: 0; padding: 14px; border: 1px solid var(--border); background: var(--bg-panel); }
        .an-grade__half h3 { margin: 0 0 10px; font-size: var(--fs-md); }
        .an-grade__half h3 span { margin-left: 7px; color: var(--text-muted); font-size: var(--fs-label); font-weight: normal; }
        .an-grade__half--ungraded { border-style: dashed; }
        .an-grade__table { overflow-x: auto; }
        .an-grade__row { display: grid; grid-template-columns: minmax(82px, 1fr) repeat(4, minmax(58px, auto)); gap: 8px; align-items: baseline; min-width: 390px; padding: 6px 0; border-top: 1px solid var(--border); color: var(--text-secondary); font-family: var(--font-mono); font-size: var(--fs-label); text-align: right; }
        .an-grade__row span:first-child { color: var(--text-primary); font-family: var(--font-sans); text-align: left; }
        .an-grade__row--head { padding-top: 0; border-top: 0; color: var(--text-muted); font-family: var(--font-sans); font-size: var(--fs-micro); }
        .an-grade__row--head span { white-space: nowrap; }
        .an-empty { margin: 40px 0; color: var(--text-secondary); font-family: var(--font-label); }
        @media (max-width: 700px) { .an-facts, .an-grade__halves { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
        @media (max-width: 640px) { .an-day { display: none; } .an-main { width: min(100% - 24px, 960px); padding-top: 28px; } .an-grade__halves { grid-template-columns: 1fr; } }
      `}</style>
    </div>
  );
}
