import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import type maplibregl from "maplibre-gl";
import type {
  SpRow,
  Palette,
  ViewMode,
  ExposuresResponse,
  ConstraintReach,
  MapOverview,
  RankedConstraints,
  ScoreboardHeadline,
} from "./api/types";
import {
  fetchTopology,
  fetchMapExposures,
  fetchMapReach,
  fetchMapOverview,
  fetchMapConstraintsRanked,
  fetchScoreboardHeadline,
} from "./api/client";
import { formatCT } from "./lib/time";
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
  forecastErrorColor,
  FORECAST_ERROR_GRADIENT_CSS,
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
import SidePanel, {
  type NetworkStats,
} from "./components/panels/SidePanel";
import { CURATED_EVENTS, type CuratedEvent } from "./lib/events";

type ConnectionState = "ok" | "error" | "loading";

interface HoveredSp {
  spId: string;
  props: Record<string, unknown>;
  // Which pane the node was touched on, so its card renders in that pane and
  // (in dual) whether it shows SF drivers. The decomposition itself is
  // side-independent — every card shows forecast / realized / error.
  side: "prediction" | "actual";
  spState: {
    predicted: number | null;
    market: number | null;
    error: number | null;
    marketSpp: number | null;
  } | null;
}

export default function App() {
  const [topology, setTopology] = useState<unknown | null>(null);
  // Two orthogonal axes. `viewMode` picks the layout: `forecastError` (default
  // landing) is a single map of P50 forecast − realized congestion; `dual` is the
  // prediction | ERCOT compare. `palette` picks the ERCOT quantity the dual panes
  // color by; forecast error is congestion-based regardless of palette.
  const [viewMode, setViewMode] = useState<ViewMode>("forecastError");
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

  const [showConstraints, setShowConstraints] = useState(true);
  // The de-piled overview (top-N constraints at their |SF|² cores + type) — the
  // sole constraint presentation on the map. Fixed per refit, so fetched once,
  // not time-indexed. `null` while loading or on 503 (map renders without it).
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
  // Forecast-error (P50 forecast − realized congestion) window-wide stats, for the
  // diverging palette centered at 0 in the forecast-error view. Computed once per
  // window load from the forecast and realized caches; the per-hour error rows are
  // derived below.
  const [errorStats, setErrorStats] =
    useState<ModeledCongestionStats | null>(null);
  // The rolling backtest scorecard for the side panel. Fetched once (the board
  // is static), independent of the forecast/playback window. `null` on 503 (no
  // board loaded) — the panel then shows network stats alone.
  const [headline, setHeadline] = useState<ScoreboardHeadline | null>(null);
  // The per-day ranked constraint list for the side panel's `Constraints` tab
  // (plan/0103). `basis` toggles predicted (default) vs realized μ; the list is
  // keyed to the cursor's CT delivery day so the realized toggle can reach a past
  // day's published DAM prices. `null` on 503 (no artifact for the day) — the tab
  // then shows its empty state.
  const [ranked, setRanked] = useState<RankedConstraints | null>(null);
  const [rankedLoading, setRankedLoading] = useState(false);
  const [constraintBasis, setConstraintBasis] =
    useState<"predicted" | "realized">("predicted");
  // Synced hover (plan/0103 Group 4): the constraint isolated across BOTH the
  // Constraints panel and the map overview. A panel-row hover and a map-mark hover
  // both write here, and both read it, so hovering either isolates that constraint
  // everywhere — the panel row lights and every other overview mark dims.
  const [hoveredConstraintId, setHoveredConstraintId] =
    useState<string | null>(null);
  // Focus-reach view (plan/0103): the src/sink dipole SP-coloring for the
  // hovered/locked constraint — its constituent nodes glow signed, every other node
  // fades to the no-data fill (the forecast-error palette is hidden while focused).
  // Separate from `reach` (the node-explorer click that opens the DetailCard) so a
  // hover just recolors nodes. `focusLockedRef` freezes it on click so panning/
  // zooming doesn't clear it; a map-background click or a fresh hover resets. Cached
  // per constraint so sweeping the list doesn't spam /map/reach.
  const [focusReach, setFocusReach] = useState<ConstraintReach | null>(null);
  const focusLockedRef = useRef(false);
  const focusIdRef = useRef<string | null>(null);
  const focusReqRef = useRef(0);
  const focusReachCache = useRef<Map<string, ConstraintReach>>(new Map());
  // The SP a constituent row in the panel's expanded list is hovering — rings that
  // node white on the map so the row and the node point at each other.
  const [hoveredMemberSp, setHoveredMemberSp] = useState<string | null>(null);
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

  // Constraint overview load — once, independent of the playback window (the SF
  // structure is fixed per refit). Soft-fails to null (no overlay) on 503.
  useEffect(() => {
    fetchMapOverview(70, 6)
      .then((o) => setOverview(o))
      .catch(() => setOverview(null));
  }, []);

  // Scorecard headline — once; the backtest board is static and independent of
  // the forecast/playback window. Soft-fails to null (scorecard hidden) on 503.
  useEffect(() => {
    fetchScoreboardHeadline()
      .then((h) => setHeadline(h))
      .catch(() => setHeadline(null));
  }, []);

  // The cursor's CT delivery day — the day the `Constraints` tab ranks. Derived
  // from the current frame's Central date (ERCOT operates on Central), so the
  // ranking follows the map's day. Undefined before a window loads → the server
  // defaults to the forecast run's latest built day.
  const deliveryDay = useMemo<string | undefined>(() => {
    const ts = timestamps[currentIndex];
    return ts ? formatCT(ts, "yyyy-MM-dd") : undefined;
  }, [timestamps, currentIndex]);

  // Ranked constraints for the panel — refetched only when the ranked DAY or the
  // basis changes (not every hour: the ranking is per delivery day). A request-id
  // guard drops a stale in-flight response. Soft-fails to null (empty state) on 503.
  const rankedReqRef = useRef(0);
  useEffect(() => {
    const token = ++rankedReqRef.current;
    setRankedLoading(true);
    fetchMapConstraintsRanked(constraintBasis, deliveryDay)
      .then((r) => {
        if (rankedReqRef.current === token) setRanked(r);
      })
      .catch(() => {
        if (rankedReqRef.current === token) setRanked(null);
      })
      .finally(() => {
        if (rankedReqRef.current === token) setRankedLoading(false);
      });
  }, [deliveryDay, constraintBasis]);

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

  // Forecast-error rows for the current hour: P50 forecast − realized congestion
  // per SP, derived client-side from the two series already in state (no new API).
  // An SP without both a forecast and a realized value rides through with a null
  // error. Empty when no forecast covers the hour (the error needs a prediction).
  const errorRows = useMemo<SpRow[]>(() => {
    if (!forecastRows.length) return [];
    const marketById = new Map(spRows.map((r) => [r.sp_id, r.congestion]));
    return forecastRows.map((f) => {
      const m = marketById.get(f.sp_id);
      const error =
        f.congestion != null && m != null ? f.congestion - m : null;
      return { sp_id: f.sp_id, congestion: error, spp: null };
    });
  }, [forecastRows, spRows]);

  // Network stats for the side panel, from state already in hand: the cursor
  // hour, that hour's realized rows, and the forecast rows. `systemLambda` is the
  // forecast entry's DAM system-λ at the cursor; `congestionAbsTotal` is Σ|C|
  // over the realized rows this hour. `modelNodes`/`ercotNodes` are the SP counts
  // on each side — the model forecasts its full nodal universe, ERCOT lights only
  // priced nodes, so model ≥ ercot. (Window / hours / cursor live on the scrubber.)
  const networkStats = useMemo<NetworkStats>(() => {
    const cur = timestamps[currentIndex] ?? null;
    const fc = cur ? getForecastCached(cur) : null;
    let absTotal: number | null = null;
    let ercot = 0;
    for (const r of spRows) {
      if (r.congestion != null) {
        ercot++;
        absTotal = (absTotal ?? 0) + Math.abs(r.congestion);
      }
    }
    let model = 0;
    for (const r of forecastRows) if (r.congestion != null) model++;
    return {
      forecastRunId,
      systemLambda: fc?.system_lambda ?? null,
      congestionAbsTotal: absTotal,
      modelNodes: model,
      ercotNodes: ercot,
    };
  }, [timestamps, currentIndex, spRows, forecastRows, forecastRunId]);

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
          // Forecast-error side: P50 forecast − realized congestion per (SP, hour)
          // where both are present, so the diverging error palette is anchored to
          // the error magnitude range (not the market's).
          const allError: Array<number | null> = [];
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
                if (sp.p50 != null && m != null) allError.push(sp.p50 - m);
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
          setErrorStats(
            allError.length ? computeModeledCongestionStats(allError) : null
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

  // The full forecast / realized / error decomposition for one SP — carried by
  // every card in every view, so the error-default never hides raw magnitude.
  // Side-independent: predicted from the forecast rows, market from the realized
  // rows, error = predicted − market when both exist.
  const spDecomp = useCallback(
    (spId: string) => {
      const f = forecastRows.find((r) => r.sp_id === spId);
      const m = spRows.find((r) => r.sp_id === spId);
      const predicted = f?.congestion ?? null;
      const market = m?.congestion ?? null;
      const error =
        predicted != null && market != null ? predicted - market : null;
      return { predicted, market, error, marketSpp: m?.spp ?? null };
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

  // ── Constraint focus (plan/0103): hover isolates + recolors, click locks ─────
  // Load a constraint's reach (cached) into the focus-reach view.
  const loadFocusReach = useCallback((id: string) => {
    const cached = focusReachCache.current.get(id);
    if (cached) {
      setFocusReach(cached);
      return;
    }
    const token = ++focusReqRef.current;
    fetchMapReach(id)
      .then((r) => {
        if (r) focusReachCache.current.set(id, r);
        if (focusReqRef.current === token) setFocusReach(r);
      })
      .catch(() => {
        if (focusReqRef.current === token) setFocusReach(null);
      });
  }, []);

  // Hover a constraint (panel row or overview mark): isolate it and recolor its
  // nodes. Leaving (id === null) resets — unless a click has locked the view, so it
  // survives while the user pans/zooms.
  const handleConstraintHover = useCallback(
    (id: string | null) => {
      if (id == null) {
        if (focusLockedRef.current) return;
        focusIdRef.current = null;
        setHoveredConstraintId(null);
        setFocusReach(null);
        focusReqRef.current++;
        return;
      }
      // Re-hovering the currently locked constraint (e.g. its own core while
      // panning) must not unlock it.
      if (focusLockedRef.current && id === focusIdRef.current) return;
      focusLockedRef.current = false;
      focusIdRef.current = id;
      setHoveredConstraintId(id);
      loadFocusReach(id);
    },
    [loadFocusReach]
  );

  // Click a constraint: lock the focus so mouse-out won't clear it.
  const handleConstraintLock = useCallback(
    (id: string) => {
      focusLockedRef.current = true;
      focusIdRef.current = id;
      setHoveredConstraintId(id);
      loadFocusReach(id);
    },
    [loadFocusReach]
  );

  const clearFocus = useCallback(() => {
    focusLockedRef.current = false;
    focusIdRef.current = null;
    focusReqRef.current++;
    setHoveredConstraintId(null);
    setFocusReach(null);
  }, []);

  // Card driver-row click: load the constraint's member list into the card AND
  // lock the map isolation, so the isolated view the user saw on hover persists
  // after the pointer leaves the row — until a background click or another
  // selection. Mirrors the constraint-panel's click-locks-hover contract, plus
  // the card's reach body.
  const handleConstraintSelectFromCard = useCallback(
    (key: string) => {
      handleConstraintClick(key);
      handleConstraintLock(key);
    },
    [handleConstraintClick, handleConstraintLock]
  );

  // Card member-row click: open that node's card (pinning + highlighting it) and
  // drop the locked constraint isolation, so the click moves the locked focus
  // from the constraint to the node. The SP lookup mirrors a map marker click so
  // the card body (sp_type / load_zone) populates the same way.
  const handleMemberSelect = useCallback(
    (sp: string) => {
      setHoveredMemberSp(null);
      clearFocus();
      const feat = spPoints?.features.find(
        (f) => (f.properties?.sp_id as string | undefined) === sp
      );
      const props = (feat?.properties ?? { sp_id: sp }) as Record<
        string,
        unknown
      >;
      handleSpClickPrediction(sp, props);
    },
    [spPoints, handleSpClickPrediction, clearFocus]
  );

  // Background (empty-map) click clears whichever mode is active.
  const handleMapBackgroundClick = useCallback(() => {
    handleClearPinnedSp();
    handleCloseReach();
    clearFocus();
  }, [handleClearPinnedSp, handleCloseReach, clearFocus]);

  // Switch the view axis, applying that view's SF-overlay default: on in the
  // forecast-error view (the overlay is that view's mechanism), off in dual (a
  // per-pane explainer). The manual overlay toggle then persists until the next
  // view switch.
  const handleViewMode = useCallback((v: ViewMode) => {
    setViewMode(v);
    setShowConstraints(v === "forecastError");
  }, []);

  // Keep a pinned SP's decomposition fresh as playback advances.
  useEffect(() => {
    if (!pinnedSp) return;
    const fresh = spDecomp(pinnedSp.spId);
    const cur = pinnedSp.spState;
    if (
      fresh.predicted !== cur?.predicted ||
      fresh.market !== cur?.market ||
      fresh.error !== cur?.error ||
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
  // The pane subtitle. A bold title line names what the pane shows; the meta row
  // reports node coverage in words — `litNoun` says what "having a value" means
  // for this pane (forecast / priced / compared) so the count reads plainly.
  const badgeFor = (
    label: string,
    lit: number = litCount,
    litNoun = "priced",
    litHint = "Nodes with a value at this hour (colored on the map); the rest are drawn unlit"
  ) => (
    <>
      <span className="pane-badge__title">{label}</span>
      <span className="pane-badge__meta">
        {spTopologyEmpty ? (
          <span className="pane-badge__stat">no nodes (rebuild topology cache)</span>
        ) : (
          <>
            <span
              className="pane-badge__stat"
              title="Settlement points (nodes) drawn on the map"
            >
              <span className="pane-badge__key">nodes</span>{" "}
              <b>{featCount.toLocaleString()}</b>
            </span>
            <span className="pane-badge__stat" title={litHint}>
              <span className="pane-badge__key">{litNoun}</span>{" "}
              <b>{lit.toLocaleString()}</b>
            </span>
          </>
        )}
      </span>
    </>
  );


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
      ? `Prediction Model: forecast ${forecastRunId}`
      : "Prediction Model: no forecast this window";

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
        showConstraints={showConstraints}
        reach={reach}
        overview={overview}
        isolatedConstraint={hoveredConstraintId}
        onIsolateConstraint={handleConstraintHover}
        onIsolateLock={handleConstraintLock}
        focusReach={focusReach}
        ringedSpId={hoveredMemberSp}
      />
      <div className="pane-badge">
        {badgeFor(
          predictionLabel,
          litFor(leftRows),
          "forecast",
          "Nodes the model forecasts a value for at this hour (colored on the map). The model covers its full nodal universe — including resource nodes (RN / CC / PUN) that ERCOT publishes no settlement price for — so this exceeds the ERCOT priced count."
        )}
      </div>
      <Legend
        palette={palette}
        rows={leftRows}
        lmpStats={leftLmpStats}
        mcStats={leftMcStats}
        constraintOverlay={showConstraints && !!overview?.constraints.length}
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
        onSelectConstraint={handleConstraintSelectFromCard}
        onHoverConstraint={handleConstraintHover}
        onHoverMember={setHoveredMemberSp}
        onSelectMember={handleMemberSelect}
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
      <div className="pane-badge">
        {badgeFor(
          "ERCOT: Day Ahead Market (DAM)",
          litCount,
          "priced",
          "Nodes with a published ERCOT DAM settlement price (SPP) at this hour (colored on the map). Resource nodes (RN / CC / PUN) carry no published price, so this is fewer than the model's forecast count."
        )}
      </div>
      <Legend
        palette={palette}
        rows={spRows}
        lmpStats={sppStats}
        mcStats={congestionStats}
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

  // Forecast-error view: a single full-width map colored by P50 forecast −
  // realized congestion on the diverging palette (forced congestion, its own
  // error-anchored stats), SF overlay on. Interactions route through the
  // prediction handlers so the card carries the decomposition + SF drivers, same
  // as the dual left pane.
  const errorLit = errorRows.filter((r) => r.congestion != null).length;
  const errorLabel =
    hasForecast && forecastRunId
      ? "Forecast Error: Prediction Model − ERCOT DAM"
      : "Forecast Error: no forecast this window";
  const errorPane = (
    <>
      <GridMap
        points={spPoints}
        rows={errorRows}
        palette="congestion"
        lmpStats={null}
        mcStats={errorStats}
        onMapClick={handleMapBackgroundClick}
        selectedSpId={pinnedSp?.spId ?? null}
        side="prediction"
        onSpHover={handleSpHoverMain}
        onSpClick={handleSpClickPrediction}
        onMapReady={handleMainReady}
        showConstraints={showConstraints}
        reach={reach}
        overview={overview}
        isolatedConstraint={hoveredConstraintId}
        onIsolateConstraint={handleConstraintHover}
        onIsolateLock={handleConstraintLock}
        focusReach={focusReach}
        ringedSpId={hoveredMemberSp}
        congestionColor={forecastErrorColor}
      />
      <div className="pane-badge">
        {badgeFor(
          errorLabel,
          errorLit,
          "compared",
          "Nodes with both a model forecast and a realized value, so an error is defined"
        )}
      </div>
      <Legend
        palette="congestion"
        rows={errorRows}
        lmpStats={null}
        mcStats={errorStats}
        titleOverride="Congestion Forecast Error · Forecast − Realized ($/MWh)"
        signLabels={{ neg: "Under", pos: "Over" }}
        barGradientOverride={FORECAST_ERROR_GRADIENT_CSS}
        constraintOverlay={showConstraints && !!overview?.constraints.length}
        overviewTypes={showConstraints && !!overview?.constraints.length}
      />
      {/* Forecast-error card: the node's forecast / realized / error + SF drivers. */}
      <DetailCard
        hoveredSp={hoveredSp?.side === "prediction" ? hoveredSp : null}
        pinnedSp={pinnedSp?.side === "prediction" ? pinnedSp : null}
        exposures={exposures}
        exposuresLoading={exposuresLoading}
        reach={reach}
        onClose={handleClearPinnedSp}
        onCloseReach={handleCloseReach}
        onSelectConstraint={handleConstraintSelectFromCard}
        onHoverConstraint={handleConstraintHover}
        onHoverMember={setHoveredMemberSp}
        onSelectMember={handleMemberSelect}
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
          overview?.constraints.length ? setShowConstraints : undefined
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
        {/* Forecast error = single map of P50 forecast − realized (default
            landing). Dual = prediction | ERCOT split, both under the active palette. */}
        {/* Map area 5 : side panel 2 → panel is ~2/7 (a bit under a third), wide
            enough that the constraint list/table don't wrap without overshooting. */}
        <div style={{ flex: 5, position: "relative" }}>
          {viewMode === "forecastError" ? (
            <div className="forecast-error-single">{errorPane}</div>
          ) : (
            <CompareMap main={leftPane} right={rightPane} />
          )}
          <style>{`
            .forecast-error-single {
              width: 100%;
              height: 100%;
              position: relative;
            }
            .pane-badge {
              position: absolute;
              top: 10px;
              left: 10px;
              padding: 5px 10px;
              background: var(--bg-glass);
              border: 1px solid var(--border);
              border-radius: 4px;
              display: flex;
              flex-direction: column;
              gap: 3px;
              /* Click-through except on the stat chips (which carry tooltips). */
              pointer-events: none;
            }
            .pane-badge__title {
              font-family: var(--font-label);
              font-weight: 600;
              font-size: var(--fs-md);
              letter-spacing: var(--track-label);
              color: var(--text-primary);
            }
            .pane-badge__meta {
              display: flex;
              gap: 18px;
              font-family: var(--font-label);
              font-weight: var(--fw-label);
              font-size: var(--fs-body);
              letter-spacing: var(--track-label);
              color: var(--text-secondary);
            }
            .pane-badge__stat { pointer-events: auto; cursor: help; }
            .pane-badge__key { color: var(--text-muted); }
            .pane-badge__stat b { color: var(--text-primary); font-weight: 600; }
          `}</style>
        </div>

        {/* Right side panel: [Stats] (network + scorecard) | [Constraints] (the
            per-day ranked list) in one tabbed region. Row click traces the
            constraint on the map via /map/reach (same as a marker click); the
            synced hover is wired in the next group. */}
        <SidePanel
          network={networkStats}
          headline={headline}
          ranked={ranked}
          rankedLoading={rankedLoading}
          constraintBasis={constraintBasis}
          onConstraintBasis={setConstraintBasis}
          onSelectConstraint={handleConstraintLock}
          highlightedConstraintId={hoveredConstraintId}
          onHoverConstraint={handleConstraintHover}
          onMemberHover={setHoveredMemberSp}
        />
      </div>

      {/* Bottom scrubber: Load Window picker sits in the scrubber's left column,
          above the transport controls. */}
      <PlaybackScrubber
        timestamps={timestamps}
        currentIndex={currentIndex}
        onIndexChange={setCurrentIndex}
        loading={loading}
        sparkSeries={sparkSeries}
        eventLabel={
          CURATED_EVENTS.find((e) => e.id === activeEventId)?.label ?? null
        }
        leftSlot={
          <DateRangePicker
            onLoad={handleCustomLoadWindow}
            onSelectEvent={handleSelectEvent}
            events={CURATED_EVENTS}
            activeEventId={activeEventId}
            loading={loading}
          />
        }
      />
    </div>
  );
}
