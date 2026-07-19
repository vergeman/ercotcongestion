import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import type maplibregl from "maplibre-gl";
import type {
  SpRow,
  Palette,
  ViewMode,
  ConstraintGeo,
  ExposuresResponse,
  ConstraintReach,
  MapOverview,
} from "./api/types";
import {
  fetchTopology,
  fetchMapConstraints,
  fetchMapExposures,
  fetchMapReach,
  fetchMapOverview,
} from "./api/client";
import {
  prefetchWindow,
  getErcotCached,
  getErcotSppCached,
  getForecastCached,
  getForecastRunId,
  getAvailableTimestamps,
} from "./api/prefetch";
import {
  computeLmpStats,
  computeModeledCongestionStats,
  basisColor,
  BASIS_GRADIENT_CSS,
  type LmpStats,
  type ModeledCongestionStats,
} from "./lib/colors";
import Header from "./components/layout/Header";
import GridMap from "./components/map/GridMap";
import PlaybackScrubber from "./components/playback/PlaybackScrubber";
import type { SparkPoint } from "./components/playback/TimelineSparkline";
import Legend from "./components/map/Legend";
import CompareMap from "./components/map/CompareMap";
import DateRangePicker from "./components/playback/DateRangePicker";
import DetailCard from "./components/map/DetailCard";
import { CURATED_EVENTS, type CuratedEvent } from "./lib/events";

type ConnectionState = "ok" | "error" | "loading";

interface HoveredSp {
  spId: string;
  props: Record<string, unknown>;
  // Which pane the node was touched on, so its card renders in that pane and
  // (in dual) whether it shows SF drivers. The decomposition itself is
  // side-independent — every card shows predicted / market / basis.
  side: "prediction" | "actual";
  spState: {
    predicted: number | null;
    market: number | null;
    basis: number | null;
    marketSpp: number | null;
  } | null;
}

export default function App() {
  const [topology, setTopology] = useState<unknown | null>(null);
  // Two orthogonal axes. `viewMode` picks the layout: `basis` (default landing)
  // is a single map of predicted − market congestion; `dual` is the prediction |
  // ERCOT compare. `palette` picks the ERCOT quantity the dual panes color by;
  // basis is congestion-based regardless of palette.
  const [viewMode, setViewMode] = useState<ViewMode>("basis");
  const [palette, setPalette] = useState<Palette>("congestion");
  const [timestamps, setTimestamps] = useState<Date[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [loading, setLoading] = useState(false);
  const [connState, setConnState] = useState<ConnectionState>("loading");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const [hoveredSp, setHoveredSp] = useState<HoveredSp | null>(null);
  const [pinnedSp, setPinnedSp] = useState<HoveredSp | null>(null);

  // Window-wide stats, computed once on window load and reused for every frame
  // so coloring is stable across playback. congestion → diverging palette;
  // spp → LMP palette.
  const [congestionStats, setCongestionStats] =
    useState<ModeledCongestionStats | null>(null);
  const [sppStats, setSppStats] = useState<LmpStats | null>(null);
  // Per-current-hour SP rows, merged from the congestion and SPP caches.
  const [spRows, setSpRows] = useState<SpRow[]>([]);
  // Per-timestamp series for the timeline sparkline (Σ|congestion| per hour),
  // aligned 1:1 with `timestamps`.
  const [sparkSeries, setSparkSeries] = useState<SparkPoint[]>([]);
  const [activeEventId, setActiveEventId] = useState<string | null>(null);

  // Constraint overlay (SF structure) — fixed per refit, so fetched once, not
  // time-indexed. `null` while loading or on 503 (map renders without it).
  const [constraints, setConstraints] = useState<ConstraintGeo[] | null>(null);
  const [showConstraints, setShowConstraints] = useState(true);
  // The de-piled overview (top-N constraints at their |SF|² cores + type). Fetched
  // once per refit; when present it replaces the flat centroid overlay on the map.
  const [overview, setOverview] = useState<MapOverview | null>(null);
  // Forecast side of the split map (left/prediction pane): per-hour P10/P50/P90
  // congestion for the current forecast run, read hour-for-hour off the same
  // scrubber as the realized right pane. `forecastRows` is the current hour;
  // the stats are window-wide (computed once on load) so coloring is stable;
  // `forecastRunId` labels which refit is serving (null → no forecast covered
  // the window, pane falls back to the realized rows).
  const [forecastRows, setForecastRows] = useState<SpRow[]>([]);
  const [forecastCongestionStats, setForecastCongestionStats] =
    useState<ModeledCongestionStats | null>(null);
  const [forecastLmpStats, setForecastLmpStats] = useState<LmpStats | null>(null);
  const [forecastRunId, setForecastRunId] = useState<string | null>(null);
  // Basis (predicted − market congestion) window-wide stats, for the diverging
  // palette centered at 0 in the basis view. Computed once per window load from
  // the forecast and realized caches; the per-hour basis rows are derived below.
  const [basisStats, setBasisStats] =
    useState<ModeledCongestionStats | null>(null);
  // Node-explorer click: top-k constraints driving the pinned SP.
  const [exposures, setExposures] = useState<ExposuresResponse | null>(null);
  const [exposuresLoading, setExposuresLoading] = useState(false);
  // Constraint click: the reach (signed SP fade + corridor). Wins the map.
  const [reach, setReach] = useState<ConstraintReach | null>(null);

  // settlement_points FeatureCollection, shared by both panes.
  const spPoints = useMemo(() => {
    if (!topology) return null;
    const t = topology as {
      settlement_points?: GeoJSON.FeatureCollection;
    };
    return (
      t.settlement_points ?? {
        type: "FeatureCollection" as const,
        features: [],
      }
    );
  }, [topology]);
  const featCount = spPoints?.features.length ?? 0;
  const spTopologyEmpty = !!topology && featCount === 0;

  // Camera sync between the two panes. Refs collected via each GridMap's
  // `onMapReady`; both handlers re-arm the mirror once both maps exist.
  const mainMapRef = useRef<maplibregl.Map | null>(null);
  const rightMapRef = useRef<maplibregl.Map | null>(null);
  const syncingSide = useRef<"main" | "right" | null>(null);
  const wireSync = useCallback(() => {
    const a = mainMapRef.current;
    const b = rightMapRef.current;
    if (!a || !b) return () => {};
    const drive =
      (from: maplibregl.Map, to: maplibregl.Map, tag: "main" | "right") =>
      () => {
        // Ignore the echo that fires while we're programmatically driving the
        // other side.
        if (syncingSide.current && syncingSide.current !== tag) return;
        syncingSide.current = tag;
        to.jumpTo({
          center: from.getCenter(),
          zoom: from.getZoom(),
          bearing: from.getBearing(),
          pitch: from.getPitch(),
        });
        syncingSide.current = null;
      };
    const aToB = drive(a, b, "main");
    const bToA = drive(b, a, "right");
    a.on("move", aToB);
    b.on("move", bToA);
    aToB();
    return () => {
      a.off("move", aToB);
      b.off("move", bToA);
    };
  }, []);
  const teardownSyncRef = useRef<(() => void) | null>(null);
  const rearmSync = useCallback(() => {
    teardownSyncRef.current?.();
    teardownSyncRef.current = wireSync();
  }, [wireSync]);
  const handleMainReady = useCallback(
    (m: maplibregl.Map) => {
      mainMapRef.current = m;
      rearmSync();
    },
    [rearmSync]
  );
  const handleRightReady = useCallback(
    (m: maplibregl.Map) => {
      rightMapRef.current = m;
      rearmSync();
    },
    [rearmSync]
  );

  // Topology load
  useEffect(() => {
    fetchTopology()
      .then((t) => {
        setTopology(t);
        setConnState("ok");
      })
      .catch(() => setConnState("error"));
  }, []);

  // Constraint overlay load — once, independent of the playback window (the SF
  // structure is fixed per refit). Soft-fails to null (no overlay) on 503.
  useEffect(() => {
    fetchMapConstraints()
      .then((c) => setConstraints(c))
      .catch(() => setConstraints(null));
    fetchMapOverview(70, 6)
      .then((o) => setOverview(o))
      .catch(() => setOverview(null));
  }, []);

  // Merge the congestion + SPP caches into per-SP rows for the current hour.
  // An SP present in only one cache still shows up, colored by whichever field
  // the active palette reads.
  useEffect(() => {
    if (!timestamps.length) return;
    const ts = timestamps[currentIndex];
    const cong = getErcotCached(ts);
    const spp = getErcotSppCached(ts);
    if (!cong && !spp) {
      setSpRows([]);
      return;
    }
    const byId = new Map<string, SpRow>();
    for (const s of cong?.sps ?? []) {
      byId.set(s.sp_id, { sp_id: s.sp_id, congestion: s.congestion, spp: null });
    }
    for (const s of spp?.sps ?? []) {
      const cur = byId.get(s.sp_id);
      if (cur) cur.spp = s.spp;
      else byId.set(s.sp_id, { sp_id: s.sp_id, congestion: null, spp: s.spp });
    }
    setSpRows(Array.from(byId.values()));
  }, [currentIndex, timestamps]);

  // Forecast rows for the current hour: P50 → congestion (the fill), P50 + the
  // hour's system-λ → spp (predicted LMP, the same reference the market side
  // subtracts). Read from the forecast cache the prefetch filled, aligned to the
  // same scrubber index as the realized rows above.
  useEffect(() => {
    if (!timestamps.length) {
      setForecastRows([]);
      return;
    }
    const fc = getForecastCached(timestamps[currentIndex]);
    if (!fc) {
      setForecastRows([]);
      return;
    }
    const lam = fc.system_lambda;
    setForecastRows(
      fc.sps.map((s) => ({
        sp_id: s.sp_id,
        congestion: s.p50,
        spp: s.p50 != null && lam != null ? s.p50 + lam : null,
      }))
    );
  }, [currentIndex, timestamps]);

  // Basis rows for the current hour: predicted − market congestion per SP,
  // derived client-side from the two series already in state (no new API). An
  // SP without both a forecast and a realized value rides through with a null
  // basis. Empty when no forecast covers the hour (basis needs a prediction).
  const basisRows = useMemo<SpRow[]>(() => {
    if (!forecastRows.length) return [];
    const marketById = new Map(spRows.map((r) => [r.sp_id, r.congestion]));
    return forecastRows.map((f) => {
      const m = marketById.get(f.sp_id);
      const basis =
        f.congestion != null && m != null ? f.congestion - m : null;
      return { sp_id: f.sp_id, congestion: basis, spp: null };
    });
  }, [forecastRows, spRows]);

  const handleLoadWindow = useCallback(
    async (start?: Date, end?: Date, cursorTs?: Date) => {
      setLoading(true);
      setConnState("loading");
      try {
        await prefetchWindow(start, end);
        const ts = getAvailableTimestamps();
        setTimestamps(ts);
        if (ts.length > 0) {
          // Window-wide stats: walk the caches so we use the deduped,
          // label-stripped entries prefetchWindow already stored.
          const allCong: Array<number | null> = [];
          const allSpp: Array<number | null> = [];
          // Forecast side: P50 (congestion) and P50 + system-λ (predicted LMP),
          // so the prediction pane can color even on a forecast-only window with
          // no realized rows.
          const allFcCong: Array<number | null> = [];
          const allFcLmp: Array<number | null> = [];
          // Basis side: predicted − market congestion per (SP, hour) where both
          // are present, so the diverging basis palette is anchored to the basis
          // magnitude range (not the market's).
          const allBasis: Array<number | null> = [];
          for (const t of ts) {
            const c = getErcotCached(t);
            if (c) for (const s of c.sps) allCong.push(s.congestion);
            const s = getErcotSppCached(t);
            if (s) for (const sp of s.sps) allSpp.push(sp.spp);
            const f = getForecastCached(t);
            if (f)
              for (const sp of f.sps) {
                allFcCong.push(sp.p50);
                allFcLmp.push(
                  sp.p50 != null && f.system_lambda != null
                    ? sp.p50 + f.system_lambda
                    : null
                );
              }
            if (c && f) {
              const marketById = new Map(
                c.sps.map((cs) => [cs.sp_id, cs.congestion])
              );
              for (const sp of f.sps) {
                const m = marketById.get(sp.sp_id);
                if (sp.p50 != null && m != null) allBasis.push(sp.p50 - m);
              }
            }
          }
          setCongestionStats(
            allCong.length ? computeModeledCongestionStats(allCong) : null
          );
          setSppStats(allSpp.length ? computeLmpStats(allSpp) : null);
          setForecastCongestionStats(
            allFcCong.length ? computeModeledCongestionStats(allFcCong) : null
          );
          setForecastLmpStats(
            allFcLmp.length ? computeLmpStats(allFcLmp) : null
          );
          setBasisStats(
            allBasis.length ? computeModeledCongestionStats(allBasis) : null
          );
          setForecastRunId(getForecastRunId());

          // Sparkline: one point per timestamp, Σ|congestion| across SPs.
          setSparkSeries(
            ts.map((t) => {
              const c = getErcotCached(t);
              let absTotal: number | null = null;
              if (c) {
                absTotal = 0;
                for (const s of c.sps) {
                  if (s.congestion != null) absTotal += Math.abs(s.congestion);
                }
              }
              return {
                modeled_congestion_abs_total: absTotal,
                n_binding_lines: null,
              };
            })
          );

          // Snap to the closest available frame if a cursor was given
          // (curated event); otherwise start at the beginning.
          if (cursorTs) {
            const target = cursorTs.getTime();
            let bestIdx = 0;
            let bestDelta = Infinity;
            for (let i = 0; i < ts.length; i++) {
              const d = Math.abs(ts[i].getTime() - target);
              if (d < bestDelta) {
                bestDelta = d;
                bestIdx = i;
              }
            }
            setCurrentIndex(bestIdx);
          } else {
            setCurrentIndex(0);
          }
          setLastUpdated(new Date());
          setConnState("ok");
        } else {
          setConnState("error");
        }
      } catch {
        setConnState("error");
      } finally {
        setLoading(false);
      }
    },
    []
  );

  // Curated events: load window, snap cursor, optionally switch palette.
  const handleSelectEvent = useCallback(
    (event: CuratedEvent) => {
      setActiveEventId(event.id);
      if (event.suggested_view) setPalette(event.suggested_view);
      handleLoadWindow(
        new Date(event.window_start),
        new Date(event.window_end),
        new Date(event.cursor_ts)
      );
    },
    [handleLoadWindow]
  );

  // Date picker wrapper — clears event selection on custom load.
  const handleCustomLoadWindow = useCallback(
    (start: Date, end: Date) => {
      setActiveEventId(null);
      handleLoadWindow(start, end);
    },
    [handleLoadWindow]
  );

  // Landing view: no explicit window — the forecast's latest operating day
  // defines the default window (prediction leads; the realized ranges are fetched
  // to match), with the cursor snapped to now. Runs once; the user can then scrub
  // or load a custom window. Placed after handleLoadWindow so its dep is in scope.
  useEffect(() => {
    handleLoadWindow(undefined, undefined, new Date());
  }, [handleLoadWindow]);

  // The full predicted / market / basis decomposition for one SP — carried by
  // every card in every view, so basis-default never hides raw magnitude.
  // Side-independent: predicted from the forecast rows, market from the realized
  // rows, basis = predicted − market when both exist.
  const spDecomp = useCallback(
    (spId: string) => {
      const f = forecastRows.find((r) => r.sp_id === spId);
      const m = spRows.find((r) => r.sp_id === spId);
      const predicted = f?.congestion ?? null;
      const market = m?.congestion ?? null;
      const basis =
        predicted != null && market != null ? predicted - market : null;
      return { predicted, market, basis, marketSpp: m?.spp ?? null };
    },
    [forecastRows, spRows]
  );

  const handleSpHover = useCallback(
    (
      side: "prediction" | "actual",
      spId: string | null,
      props: Record<string, unknown> | null
    ) => {
      if (!spId || !props) {
        setHoveredSp(null);
        return;
      }
      setHoveredSp({ spId, props, side, spState: spDecomp(spId) });
    },
    [spDecomp]
  );
  const handleSpHoverMain = useCallback(
    (spId: string | null, props: Record<string, unknown> | null) =>
      handleSpHover("prediction", spId, props),
    [handleSpHover]
  );
  const handleSpHoverRight = useCallback(
    (spId: string | null, props: Record<string, unknown> | null) =>
      handleSpHover("actual", spId, props),
    [handleSpHover]
  );

  // Request-id guards so a slow in-flight fetch can't clobber a newer click.
  const exposureReqRef = useRef(0);
  const reachReqRef = useRef(0);

  // Prediction-pane click: pin the node and trace its SF drivers (the overview /
  // reach machinery lives on this pane).
  const handleSpClickPrediction = useCallback(
    (spId: string, props: Record<string, unknown>) => {
      setReach(null); // a node click leaves constraint-reach mode
      reachReqRef.current++;
      setPinnedSp({
        spId,
        props,
        side: "prediction",
        spState: spDecomp(spId),
      });
      const token = ++exposureReqRef.current;
      setExposures(null);
      setExposuresLoading(true);
      fetchMapExposures(spId)
        .then((r) => {
          if (exposureReqRef.current === token) setExposures(r);
        })
        .catch(() => {
          if (exposureReqRef.current === token) setExposures(null);
        })
        .finally(() => {
          if (exposureReqRef.current === token) setExposuresLoading(false);
        });
    },
    [spDecomp]
  );

  // Actual-pane click: pin the node scoped to the realized values only — no SF
  // drivers (those belong to the prediction pane), so drop any in-flight fetch.
  const handleSpClickActual = useCallback(
    (spId: string, props: Record<string, unknown>) => {
      setReach(null);
      reachReqRef.current++;
      setExposures(null);
      setExposuresLoading(false);
      exposureReqRef.current++;
      setPinnedSp({
        spId,
        props,
        side: "actual",
        spState: spDecomp(spId),
      });
    },
    [spDecomp]
  );

  const handleClearPinnedSp = useCallback(() => {
    setPinnedSp(null);
    setExposures(null);
    setExposuresLoading(false);
    exposureReqRef.current++;
  }, []);

  // Constraint click (map marker or a driver row) → trace its reach; leaves the
  // node-explorer view. handleCloseReach / a background click return to normal.
  const handleConstraintClick = useCallback((constraintKey: string) => {
    setPinnedSp(null);
    setExposures(null);
    exposureReqRef.current++;
    const token = ++reachReqRef.current;
    fetchMapReach(constraintKey)
      .then((r) => {
        if (reachReqRef.current === token) setReach(r);
      })
      .catch(() => {
        if (reachReqRef.current === token) setReach(null);
      });
  }, []);

  const handleCloseReach = useCallback(() => {
    setReach(null);
    reachReqRef.current++;
  }, []);

  // Background (empty-map) click clears whichever mode is active.
  const handleMapBackgroundClick = useCallback(() => {
    handleClearPinnedSp();
    handleCloseReach();
  }, [handleClearPinnedSp, handleCloseReach]);

  // Switch the view axis, applying that view's SF-overlay default: on in basis
  // (the overlay is the basis mechanism), off in dual (a per-pane explainer).
  // The manual overlay toggle then persists until the next view switch.
  const handleViewMode = useCallback((v: ViewMode) => {
    setViewMode(v);
    setShowConstraints(v === "basis");
  }, []);

  // Which constraint centroids glow on the overlay: the pinned node's drivers,
  // or the single constraint being reached.
  const highlightedConstraints = useMemo(() => {
    if (reach) return new Set([reach.constraint_key]);
    if (exposures)
      return new Set(exposures.exposures.map((e) => e.constraint_key));
    return new Set<string>();
  }, [reach, exposures]);

  // Keep a pinned SP's decomposition fresh as playback advances.
  useEffect(() => {
    if (!pinnedSp) return;
    const fresh = spDecomp(pinnedSp.spId);
    const cur = pinnedSp.spState;
    if (
      fresh.predicted !== cur?.predicted ||
      fresh.market !== cur?.market ||
      fresh.basis !== cur?.basis ||
      fresh.marketSpp !== cur?.marketSpp
    ) {
      setPinnedSp({ ...pinnedSp, spState: fresh });
    }
  }, [spRows, forecastRows]); // eslint-disable-line react-hooks/exhaustive-deps

  // The forecast covers this hour when its cache had a row for it. When it does,
  // the left pane shows the forecast; otherwise it renders empty — we do NOT fall
  // back to the realized rows (duplicating the ERCOT pane hid the fact that there
  // was no prediction). `forecastRows` is already [] without a forecast.
  const hasForecast = forecastRows.length > 0;
  const leftRows = forecastRows;
  // Color the forecast on the realized scale when both exist, so the two panes
  // are directly comparable; fall back to the forecast's own scale on a
  // forecast-only window (tomorrow, no realized rows yet).
  const leftMcStats = congestionStats ?? forecastCongestionStats;
  const leftLmpStats = sppStats ?? forecastLmpStats;

  const litFor = (rows: SpRow[]) =>
    rows.filter((r) => (palette === "lmp" ? r.spp != null : r.congestion != null))
      .length;
  const litCount = litFor(spRows);
  const badgeFor = (label: string, lit: number = litCount) =>
    spTopologyEmpty
      ? `${label} · no SPs (rebuild topology cache)`
      : `${label} · ${featCount} SPs · ${lit} lit`;

  // Shared across both panes. Per-side hover/click handlers are passed
  // separately so each card renders in — and reads — its own pane.
  const paneProps = {
    points: spPoints,
    rows: spRows,
    palette,
    lmpStats: sppStats,
    mcStats: congestionStats,
    onMapClick: handleMapBackgroundClick,
    selectedSpId: pinnedSp?.spId ?? null,
  };

  // The forecast pane's label: which refit is serving + the served day (the
  // cursor hour's date), or the realized fallback.
  const predictionLabel =
    hasForecast && forecastRunId
      ? `PREDICTION · forecast ${forecastRunId}`
      : "PREDICTION · no forecast this window";

  const leftPane = (
    <>
      <GridMap
        {...paneProps}
        rows={leftRows}
        lmpStats={leftLmpStats}
        mcStats={leftMcStats}
        side="prediction"
        onSpHover={handleSpHoverMain}
        onSpClick={handleSpClickPrediction}
        onMapReady={handleMainReady}
        constraints={constraints}
        showConstraints={showConstraints}
        highlightedConstraints={highlightedConstraints}
        onConstraintClick={handleConstraintClick}
        reach={reach}
        overview={overview}
      />
      <div className="pane-badge">
        {badgeFor(predictionLabel, litFor(leftRows))}
      </div>
      <Legend
        palette={palette}
        rows={leftRows}
        lmpStats={leftLmpStats}
        mcStats={leftMcStats}
        variant="palette-only"
        paneLabel={
          hasForecast && forecastRunId
            ? `PREDICTION · forecast ${forecastRunId}`
            : "PREDICTION · no forecast this window"
        }
        constraintOverlay={showConstraints && !!constraints?.length}
        overviewTypes={showConstraints && !!overview?.constraints.length}
      />
      {/* Prediction card: the node's forecast readout + its SF drivers. */}
      <DetailCard
        hoveredSp={hoveredSp?.side === "prediction" ? hoveredSp : null}
        pinnedSp={pinnedSp?.side === "prediction" ? pinnedSp : null}
        exposures={exposures}
        exposuresLoading={exposuresLoading}
        reach={reach}
        onClose={handleClearPinnedSp}
        onCloseReach={handleCloseReach}
        onSelectConstraint={handleConstraintClick}
      />
    </>
  );

  const rightPane = (
    <>
      <GridMap
        {...paneProps}
        side="actual"
        onSpHover={handleSpHoverRight}
        onSpClick={handleSpClickActual}
        onMapReady={handleRightReady}
      />
      <div className="pane-badge">{badgeFor("ERCOT · actual")}</div>
      <Legend
        palette={palette}
        rows={spRows}
        lmpStats={sppStats}
        mcStats={congestionStats}
        variant="full"
        paneLabel="ERCOT · actual"
      />
      {/* Actual card: the node's realized readout only — no SF drivers (those
          are a prediction-side concern). */}
      <DetailCard
        hoveredSp={hoveredSp?.side === "actual" ? hoveredSp : null}
        pinnedSp={pinnedSp?.side === "actual" ? pinnedSp : null}
        showDrivers={false}
        onClose={handleClearPinnedSp}
      />
    </>
  );

  // Basis view: a single full-width map colored by predicted − market congestion
  // on the diverging palette (forced congestion, its own basis-anchored stats),
  // SF overlay on. Interactions route through the prediction handlers so the card
  // carries the decomposition + SF drivers, same as the dual left pane.
  const basisLit = basisRows.filter((r) => r.congestion != null).length;
  const basisLabel =
    hasForecast && forecastRunId
      ? `BASIS · forecast ${forecastRunId} − ERCOT`
      : "BASIS · no forecast this window";
  const basisPane = (
    <>
      <GridMap
        points={spPoints}
        rows={basisRows}
        palette="congestion"
        lmpStats={null}
        mcStats={basisStats}
        onMapClick={handleMapBackgroundClick}
        selectedSpId={pinnedSp?.spId ?? null}
        side="prediction"
        onSpHover={handleSpHoverMain}
        onSpClick={handleSpClickPrediction}
        onMapReady={handleMainReady}
        constraints={constraints}
        showConstraints={showConstraints}
        highlightedConstraints={highlightedConstraints}
        onConstraintClick={handleConstraintClick}
        reach={reach}
        overview={overview}
        congestionColor={basisColor}
      />
      <div className="pane-badge">{badgeFor(basisLabel, basisLit)}</div>
      <Legend
        palette="congestion"
        rows={basisRows}
        lmpStats={null}
        mcStats={basisStats}
        variant="full"
        titleOverride="Basis · predicted − market ($/MWh)"
        signLabels={{ neg: "pred < market", pos: "pred > market" }}
        barGradientOverride={BASIS_GRADIENT_CSS}
        paneLabel={basisLabel}
        constraintOverlay={showConstraints && !!constraints?.length}
        overviewTypes={showConstraints && !!overview?.constraints.length}
      />
      {/* Basis card: the node's predicted / market / basis + its SF drivers. */}
      <DetailCard
        hoveredSp={hoveredSp?.side === "prediction" ? hoveredSp : null}
        pinnedSp={pinnedSp?.side === "prediction" ? pinnedSp : null}
        exposures={exposures}
        exposuresLoading={exposuresLoading}
        reach={reach}
        onClose={handleClearPinnedSp}
        onCloseReach={handleCloseReach}
        onSelectConstraint={handleConstraintClick}
      />
    </>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <Header
        viewMode={viewMode}
        onViewMode={handleViewMode}
        palette={palette}
        onPalette={setPalette}
        lastUpdated={lastUpdated}
        connectionState={connState}
        showConstraints={showConstraints}
        onToggleConstraints={
          constraints?.length || overview?.constraints.length
            ? setShowConstraints
            : undefined
        }
      />

      <div
        style={{
          flex: 1,
          display: "flex",
          overflow: "hidden",
          position: "relative",
        }}
      >
        {/* Basis = single map of predicted − market (default landing). Dual =
            prediction | ERCOT split, both under the active palette. */}
        <div style={{ flex: 1, position: "relative" }}>
          {viewMode === "basis" ? (
            <div className="basis-single">{basisPane}</div>
          ) : (
            <CompareMap main={leftPane} right={rightPane} />
          )}
          <style>{`
            .basis-single {
              width: 100%;
              height: 100%;
              position: relative;
            }
            .pane-badge {
              position: absolute;
              top: 10px;
              left: 10px;
              padding: 3px 8px;
              background: rgba(15, 18, 23, 0.85);
              border: 1px solid var(--border);
              border-radius: 3px;
              color: var(--text-secondary);
              font-family: 'Barlow Condensed', sans-serif;
              font-size: 10px;
              letter-spacing: 0.08em;
              text-transform: uppercase;
              pointer-events: none;
            }
          `}</style>
        </div>
      </div>

      {/* Bottom scrubber */}
      <div
        style={{
          display: "flex",
          alignItems: "stretch",
          background: "var(--bg-panel)",
          borderTop: "1px solid var(--border)",
          flexShrink: 0,
        }}
      >
        <div
          style={{
            padding: "0 12px",
            display: "flex",
            alignItems: "center",
            borderRight: "1px solid var(--border)",
          }}
        >
          <DateRangePicker
            onLoad={handleCustomLoadWindow}
            onSelectEvent={handleSelectEvent}
            events={CURATED_EVENTS}
            activeEventId={activeEventId}
            loading={loading}
          />
        </div>
        <div style={{ flex: 1 }}>
          <PlaybackScrubber
            timestamps={timestamps}
            currentIndex={currentIndex}
            onIndexChange={setCurrentIndex}
            loading={loading}
            sparkSeries={sparkSeries}
            eventLabel={
              CURATED_EVENTS.find((e) => e.id === activeEventId)?.label ?? null
            }
          />
        </div>
      </div>
    </div>
  );
}
