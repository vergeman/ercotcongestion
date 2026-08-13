import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { BriefHero, HeroSegment } from "../api/types";
import { fetchAnalysisBriefLatest, fetchBriefHero } from "../api/client";
import HeaderNav from "../components/layout/HeaderNav";
import { formatCT } from "../lib/time";
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

// v6 is deliberately a separate composition from the legacy, precomputed
// Analysis page. It owns only a delivery day; the map/matrix playback session
// remains mounted exclusively on those surfaces.
export default function BriefPage() {
  const cursor = useTimeCursor();
  const cursorDay = cursor.t ? formatCT(cursor.t, "yyyy-MM-dd") : null;
  const [defaultDay, setDefaultDay] = useState<string | null>(null);
  const [indexLoaded, setIndexLoaded] = useState(false);
  const [hero, setHero] = useState<BriefHero | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  // A cold visit has no coordinate.  The hero supplies an exact delivery-day
  // cursor; write all three fields so the first URL is immediately shareable.
  // Preserve a complete coordinate handed over by Map/Matrix, including its
  // wider load window.
  useEffect(() => {
    if (!hero?.available || !hero.cursor) return;
    if (cursor.t && cursor.ws && cursor.we) return;
    cursor.setCoord({
      t: new Date(hero.cursor.t),
      ws: new Date(hero.cursor.ws),
      we: new Date(hero.cursor.we),
    }, { replace: true });
  }, [hero, cursor]);

  const provenance = hero?.provenance;
  const basisLabel = provenance?.basis === "settled" ? "DAM settled" : "forecast";
  const title = useMemo(
    () => hero?.segments?.headline ?? [],
    [hero]
  );

  return (
    <div className="an-page">
      <header className="an-topbar">
        <HeaderNav active="brief" />
        {deliveryDay && <span className="an-day">{fmtDay(deliveryDay)}</span>}
        {provenance && <span className={`an-basis an-basis--${provenance.basis}`}>{basisLabel}</span>}
      </header>

      <main className="an-main">
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
              <div className="an-hero__meta">
                <span>Run {provenance?.run_id}</span>
                <span>{provenance?.horizon === 1 ? "final · t+1" : "preview · t+2"}</span>
                <Link to={`/map${window.location.search}`}>Open this day on the map →</Link>
              </div>
            </section>

            <Stage title="Standouts" detail="Unusual constraints, nodes, and paths will land with their query-backed rows." />
            <Stage title="Top Constraints by Shadow Price (μ)" detail="The untruncated constraint panel follows the query endpoint." />
            <Stage title="Top Nodal Congestion" detail="Nodal attribution will render from the full shift-factor column." />
            <Stage title="Source–sink pairs" detail="Path composition will render when the node and pair routes are wired into this panel." />
            <Stage title="Forecast Grade" detail="Forecast-versus-settled scoring arrives with the complete scoring universe." />
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
        .an-hero { padding-bottom: 32px; border-bottom: 2px solid var(--text-primary); }
        .an-eyebrow { margin: 0 0 8px; color: var(--text-secondary); font: var(--fw-label) var(--fs-xs) var(--font-label); letter-spacing: var(--track-label); text-transform: uppercase; }
        .an-hero h1 { max-width: 28ch; margin: 0; font-size: clamp(28px, 4vw, 44px); line-height: 1.14; letter-spacing: -0.025em; }
        .an-lede { max-width: 72ch; margin: 16px 0 0; color: var(--text-secondary); font-size: var(--fs-lg); line-height: 1.55; }
        .an-hero__meta { display: flex; flex-wrap: wrap; gap: 8px 16px; margin-top: 20px; color: var(--text-secondary); font-size: var(--fs-sm); }
        .an-hero__meta a { color: var(--accent); text-decoration: none; }
        .an-hero__meta a:hover { text-decoration: underline; }
        .an-stage { margin-top: 42px; }
        .an-stage h2 { margin: 0; font-size: var(--fs-xl); }
        .an-stage p { margin: 7px 0 0; color: var(--text-secondary); }
        .an-empty { margin: 40px 0; color: var(--text-secondary); font-family: var(--font-label); }
        @media (max-width: 640px) { .an-day { display: none; } .an-main { width: min(100% - 24px, 960px); padding-top: 28px; } }
      `}</style>
    </div>
  );
}
