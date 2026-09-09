/* eslint-disable react-hooks/set-state-in-effect */
import { useEffect, useRef, useState } from "react";
import type { BriefSelection } from "../lib/briefSelection";
import HeaderNav from "../components/layout/HeaderNav";
import HeaderStatus from "../components/layout/HeaderStatus";
import { formatCT } from "../lib/time";
import { useTimeCursor } from "../hooks/useTimeCursor";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useBriefDay } from "../hooks/useBriefDay";
import BriefDayControls from "../components/brief/BriefDayControls";
import BriefHero from "../components/brief/BriefHero";
import BriefEvidence from "../components/brief/evidence/BriefEvidence";
import { briefDayBounds, briefMapWatchHref } from "../features/brief/routes";
import BriefDetailPanel from "../components/brief/BriefDetailPanel";
import { gw, numeric, percent, usd, zoneLabel } from "../lib/format";
import { DualStatBox } from "../components/brief/BriefPrimitives";
import ForecastGrade from "../components/brief/evidence/ForecastGrade";
import StandoutsPanel from "../components/brief/evidence/StandoutsPanel";
import TopConstraintsPanel from "../components/brief/evidence/TopConstraintsPanel";
import TopNodesPanel from "../components/brief/evidence/TopNodesPanel";
import ContextPanel from "../components/brief/evidence/ContextPanel";
import "../features/brief/brief.css";

const fmtDay = (day: string) =>
  new Date(`${day}T12:00:00Z`).toLocaleDateString("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "America/Chicago",
  });

const MOBILE_BREAKPOINT = "(max-width: 700px)";

// The leading zone's signed congestion sense, for the Zone Price pair. The
// default reading of congestion is scarcity that lifts price; a negative zone
// (export/oversupply) sits below the system price, which is worth calling out.
// Sign only — the mean magnitude is node-sampling sensitive. A ±$1/MWh dead band
// leaves a flat zone unlabelled.
const priceDirection = (congestion: number | null) =>
  congestion == null || Math.abs(congestion) < 1
    ? "—"
    : congestion < 0
    ? "Below system"
    : "Above system";

// v6 is deliberately a separate composition from the legacy, precomputed
// Analysis page. It owns only a delivery day; the map/matrix playback session
// remains mounted exclusively on those surfaces.
export default function BriefPage() {
  const isMobile = useMediaQuery(MOBILE_BREAKPOINT);
  const cursor = useTimeCursor();
  const cursorDay = cursor.t ? formatCT(cursor.t, "yyyy-MM-dd") : null;
  const [detailsRetry, setDetailsRetry] = useState(0);
  const [activeEventId, setActiveEventId] = useState<string | null>(null);
  // The row a reader opened the shared detail panel over (plan/0135); null when
  // closed. Purely UI state — it never touches the Brief's time coordinate.
  const [selection, setSelection] = useState<BriefSelection | null>(null);
  const [replaceWithHeroCursor, setReplaceWithHeroCursor] = useState(false);
  const {
    deliveryDay,
    hero,
    topConstraints,
    standouts,
    topNodes,
    context,
    grade,
    gradeHistory,
    topConstraintsLoading,
    standoutsLoading,
    topNodesLoading,
    contextLoading,
    gradeLoading,
    heroError,
    detailsError,
    connectionState,
    lastUpdated,
    adjacentDays,
    heroPending,
    initialLookupDone,
    globalLoading,
  } = useBriefDay(cursorDay, detailsRetry);
  // Router search params publish on the following render. This ref records a
  // picker selection synchronously, so the current hero cannot win the brief
  // cursor during that short handoff.
  const pendingDeliveryDayRef = useRef<string | null>(null);

  // The detail panel is opened over a specific day's row; close it whenever the
  // delivery day changes so a stale selection can't survive into another day.
  useEffect(() => {
    setSelection(null);
  }, [deliveryDay]);

  // A cold visit has no coordinate.  The hero supplies an exact delivery-day
  // cursor; write all three fields so the first URL is immediately shareable.
  // Preserve a complete coordinate handed over by Map/Matrix, including its
  // wider load window.
  useEffect(() => {
    if (!hero?.available || !hero.cursor) return;
    const heroDay = hero.provenance?.delivery_date;
    const expectedDay = pendingDeliveryDayRef.current ?? deliveryDay;
    // A picker selection changes the URL before the Router and new hero have
    // both updated. Only the requested day's hero may replace that coordinate.
    if (heroDay !== expectedDay) return;
    if (!replaceWithHeroCursor && cursor.t && cursor.ws && cursor.we) return;
    cursor.setCoord(
      {
        t: new Date(hero.cursor.t),
        ws: new Date(hero.cursor.ws),
        we: new Date(hero.cursor.we),
      },
      { replace: true }
    );
    if (pendingDeliveryDayRef.current === heroDay)
      pendingDeliveryDayRef.current = null;
    setReplaceWithHeroCursor(false);
  }, [hero, cursor, replaceWithHeroCursor]);

  const provenance = hero?.provenance;
  const settled = provenance?.basis === "settled";
  const regime = hero?.slots?.regime;
  const magnitude = hero?.slots?.magnitude;
  const where = hero?.slots?.where;
  const forecastLoadTotal = numeric(regime, "today");
  const forecastLoadNet = numeric(regime, "net_load");
  const actualLoadTotal = numeric(regime, "actual_today");
  const actualLoadNet = numeric(regime, "actual_net_load");
  // T+2 is always the DAM-close forecast. On settled T+1, prefer the complete
  // realized pair, falling back to the complete forecast pair when actual load
  // data has not landed yet. Never mix the two sources within this card.
  const hasActualLoadPair = actualLoadTotal != null && actualLoadNet != null;
  const loadSource =
    provenance?.horizon == null
      ? null
      : provenance.horizon === 1 && settled && hasActualLoadPair
      ? "actual"
      : "forecast";
  const loadTotal =
    loadSource === "actual"
      ? actualLoadTotal
      : loadSource === "forecast"
      ? forecastLoadTotal
      : null;
  const loadNet =
    loadSource === "actual"
      ? actualLoadNet
      : loadSource === "forecast"
      ? forecastLoadNet
      : null;
  const loadTotalLabel =
    loadSource === "actual" ? "Total Load" : "Total Load Forecast";
  const loadNetLabel =
    loadSource === "actual" ? "Net Load" : "Net Load Forecast";
  const magnitudeValue = numeric(magnitude, "value");
  const magnitudeRank = numeric(magnitude, "rank");
  const magnitudeMedian = numeric(magnitude, "med");
  const whereShare = numeric(where, "share");
  const whereZone = typeof where?.zone === "string" ? where.zone : null;
  const whereCongestion = numeric(where, "zone_congestion");
  // The hero's own map action (0131): settled heroes open the ERCOT DAM view;
  // forecast heroes (including t+2 previews) open the latest price forecast.
  // Shared by the image CTA and its mobile fallback below.
  //
  // `t` is deliberately `cursor.ws` (the delivery day's start), not
  // `cursor.t` (the peak-μ hour `_cursor` computes it as). Autoplay starts
  // wherever the scrubber's cursor lands and only rewinds if it's already at
  // the window's end — landing mid-day would give the reader just the
  // tail of the day to watch move, not the full arc.
  const watchHref = briefMapWatchHref(hero, settled);
  const selectDeliveryDay = (day: string) => {
    const { start, end } = briefDayBounds(day);
    setActiveEventId(null);
    pendingDeliveryDayRef.current = day;
    setReplaceWithHeroCursor(true);
    cursor.setCoord({ t: start, ws: start, we: end });
  };
  return (
    <div className="an-page">
      <header className="an-topbar">
        <HeaderNav active="brief" />
        <HeaderStatus
          connectionState={connectionState}
          lastUpdated={lastUpdated}
        />
      </header>

      <main className="an-main">
        {!globalLoading && (
          <div className="an-date-picker">
            {provenance && (
              <div className="an-brief-meta">
                <span className="an-brief-meta__item">
                  <span className="an-brief-meta__label label">Model Run</span>
                  <span className="an-brief-meta__val">
                    {provenance.run_id}
                  </span>
                </span>
                <span className="an-brief-meta__item">
                  <span className="an-brief-meta__label label">Status</span>
                  <span className="an-brief-meta__val">
                    {settled ? "DAM Settled" : "Forecast"} · t+
                    {provenance.horizon}
                  </span>
                </span>
              </div>
            )}
            <BriefDayControls
              day={deliveryDay}
              adjacentDays={adjacentDays}
              loading={heroPending}
              activeEventId={activeEventId}
              onSelectDay={selectDeliveryDay}
              onSelectEvent={(event) => {
                setActiveEventId(event.id);
                cursor.setCoord({
                  t: new Date(event.cursor_ts),
                  ws: new Date(event.window_start),
                  we: new Date(event.window_end),
                });
              }}
            />
          </div>
        )}
        {globalLoading && (
          <section
            className="an-brief-loader"
            role="status"
            aria-label="Loading daily congestion brief"
          >
            <div className="an-brief-loader__brand" aria-hidden="true">
              <span className="an-brief-loader__title">ERCOT STRESS</span>
              <span className="an-brief-loader__bolt">⚡</span>
            </div>
            <span className="an-loading-indicator" aria-hidden="true" />
          </section>
        )}
        {initialLookupDone && !deliveryDay && (
          <p className="an-empty">No forecast delivery day is published yet.</p>
        )}
        {heroError && <p className="an-empty">{heroError}</p>}
        {!heroPending && hero && !hero.available && (
          <p className="an-empty">
            No forecast artifact is available for{" "}
            {deliveryDay ? fmtDay(deliveryDay) : "this day"}.
          </p>
        )}

        {!heroPending && hero?.available && hero.segments && (
          <>
            <BriefHero
              hero={hero}
              settled={settled}
              mobile={isMobile}
              watchHref={watchHref}
              evidenceLoading={false}
              evidence={
                hero && (
                  <div className="an-facts" aria-label="Brief evidence">
                    {loadTotal != null && loadNet != null && (
                      <DualStatBox
                        firstLabel={loadTotalLabel}
                        firstValue={gw(loadTotal)}
                        secondLabel={loadNetLabel}
                        secondValue={gw(loadNet)}
                      />
                    )}
                    {magnitudeValue != null && magnitudeMedian != null && (
                      <DualStatBox
                        firstLabel="Total Congestion"
                        firstValue={usd(magnitudeValue)}
                        secondLabel="Median"
                        secondValue={usd(magnitudeMedian)}
                      />
                    )}
                    {magnitudeRank != null && (
                      <DualStatBox
                        firstLabel="30-Day Congestion"
                        firstValue={`#${magnitudeRank}`}
                        secondLabel={whereZone ? "Congested Region" : undefined}
                        secondValue={
                          whereZone ? zoneLabel(whereZone) : undefined
                        }
                      />
                    )}
                    {whereZone && whereShare != null && (
                      <DualStatBox
                        firstLabel={`${zoneLabel(whereZone)} μ Footprint`}
                        firstValue={percent(whereShare)}
                        secondLabel={`${zoneLabel(whereZone)} Price`}
                        secondValue={priceDirection(whereCongestion)}
                      />
                    )}
                  </div>
                )
              }
            />

            <BriefEvidence
              error={detailsError}
              onRetry={() => setDetailsRetry((retry) => retry + 1)}
            >
              <StandoutsPanel
                data={standouts}
                loading={standoutsLoading}
                settled={settled}
                onSelect={setSelection}
              />
              <TopConstraintsPanel
                data={topConstraints}
                loading={topConstraintsLoading}
                settled={settled}
                onSelect={setSelection}
              />
              <TopNodesPanel
                data={topNodes}
                loading={topNodesLoading}
                settled={settled}
                onSelect={setSelection}
              />
              <ForecastGrade
                grade={grade}
                history={gradeHistory}
                loading={gradeLoading}
                settled={settled}
              />
              <ContextPanel data={context} loading={contextLoading} />
            </BriefEvidence>
          </>
        )}
      </main>

      <BriefDetailPanel
        selection={selection}
        settled={settled}
        heroCursor={hero?.cursor}
        onClose={() => setSelection(null)}
      />
    </div>
  );
}
