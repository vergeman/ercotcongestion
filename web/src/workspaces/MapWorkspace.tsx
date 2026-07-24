import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import type maplibregl from "maplibre-gl";
import type {
  SpRow,
  Palette,
  ViewMode,
  ExposuresResponse,
  ConstraintReach,
  MapOverview,
  MapMeta,
  RankedConstraints,
  ScoreboardHeadline,
} from "../api/types";
import {
  fetchTopology,
  fetchMapExposures,
  fetchMapReach,
  fetchMapOverview,
  fetchMapMeta,
  fetchMapConstraintsRanked,
  fetchScoreboardHeadline,
} from "../api/client";
import { formatCT } from "../lib/time";
import {
  getErcotCached,
  getErcotSppCached,
  getForecastCached,
} from "../api/prefetch";
import {
  forecastErrorColor,
  forecastErrorGradientCss,
} from "../lib/colors";
import Header from "../components/layout/Header";
import MobileDrawer from "../components/layout/MobileDrawer";
import GridMap from "../components/map/GridMap";
import Legend from "../components/map/Legend";
import CompareMap from "../components/map/CompareMap";
import DateRangePicker from "../components/playback/DateRangePicker";
import DetailCard from "../components/map/DetailCard";
import Tooltip from "../components/ui/Tooltip";
import SidePanel, {
  type NetworkStats,
} from "../components/panels/SidePanel";
import { CURATED_EVENTS, type CuratedEvent } from "../lib/events";
import { useTheme } from "../lib/theme";
import { useExplorerSession } from "../hooks/useExplorerSession";

const MOBILE_BREAKPOINT = "(max-width: 767px)";

function useMediaQuery(query: string): boolean {
  const getMatches = () =>
    typeof window !== "undefined" && window.matchMedia(query).matches;
  const [matches, setMatches] = useState(getMatches);

  useEffect(() => {
    const mediaQuery = window.matchMedia(query);
    const update = () => setMatches(mediaQuery.matches);
    update();
    mediaQuery.addEventListener("change", update);
    return () => mediaQuery.removeEventListener("change", update);
  }, [query]);

  return matches;
}

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

export interface MapWorkspaceProps {
  session: ReturnType<typeof useExplorerSession>;
  onNavigate: (workspace: "map" | "matrix") => void;
}

export default function MapWorkspace({ session, onNavigate }: MapWorkspaceProps) {
  // Mobile is intentionally a map-first experience. Keep the user's desktop
  // view choice in state, but never mount the second synchronized map below the
  // breakpoint; returning to desktop restores their chosen view.
  const isMobile = useMediaQuery(MOBILE_BREAKPOINT);
  // Re-render on theme flip so the forecast-error legend gradient (built from the
  // theme-aware palette) stays in sync with the map fills.
  useTheme();
  const [topology, setTopology] = useState<unknown | null>(null);
  // Two orthogonal axes. `viewMode` picks the layout: `forecastError` (default
  // landing) is a single map of P50 forecast − realized congestion; `dual` is the
  // prediction | ERCOT compare. `palette` picks the ERCOT quantity the dual panes
  // color by; forecast error is congestion-based regardless of palette.
  const [viewMode, setViewMode] = useState<ViewMode>("forecastError");
  const renderedViewMode = isMobile ? "forecastError" : viewMode;
  const [palette, setPalette] = useState<Palette>("congestion");
  const {
    timestamps, currentIndex, loading, connectionState: connState,
    setConnectionState: setConnState, lastUpdated, activeEventId,
    congestionStats, sppStats, forecastCongestionStats, forecastLmpStats,
    errorStats, forecastRunId, selectEvent,
    loadCustomWindow: handleCustomLoadWindow,
  } = session;
  const handleSelectEvent = useCallback(
    (event: CuratedEvent) => selectEvent(event, setPalette),
    [selectEvent]
  );
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);

  // Each map owns its own card interaction. In dual view, touching the ERCOT
  // pane must not replace or close the prediction pane's card (and vice versa).
  const [hoveredSp, setHoveredSp] = useState<Record<"prediction" | "actual", HoveredSp | null>>({
    prediction: null,
    actual: null,
  });
  const [pinnedSp, setPinnedSp] = useState<Record<"prediction" | "actual", HoveredSp | null>>({
    prediction: null,
    actual: null,
  });

  // Per-current-hour SP rows, merged from the congestion and SPP caches.
  const [spRows, setSpRows] = useState<SpRow[]>([]);

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
  // Forecast-error (P50 forecast − realized congestion) window-wide stats, for the
  // diverging palette centered at 0 in the forecast-error view. Computed once per
  // window load from the forecast and realized caches; the per-hour error rows are
  // derived below.
  // The rolling backtest scorecard for the side panel. Fetched once (the board
  // is static), independent of the forecast/playback window. `null` on 503 (no
  // board loaded) — the panel then shows network stats alone.
  const [headline, setHeadline] = useState<ScoreboardHeadline | null>(null);
  // The diagnostics for the active SF refit window. These qualify the entire
  // map/constraint view, so they belong beside the scorecard rather than inside
  // a selected node or constraint card.
  const [mapMeta, setMapMeta] = useState<MapMeta | null>(null);
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
  // Constraint focus follows an effective = hovered ?? locked model (plan/0112).
  // A click LOCKS a constraint (`lockedConstraintId`, persists until another click
  // or a background click); a hover transiently overlays a different one
  // (`hoveredConstraintId`); un-hovering reverts to the lock — hover NEVER clears
  // the lock. `effectiveConstraintId` is what the map isolates and the focus-reach
  // recolors, so both the panel and the overview honor the same rule.
  const [hoveredConstraintId, setHoveredConstraintId] =
    useState<string | null>(null);
  const [lockedConstraintId, setLockedConstraintId] =
    useState<string | null>(null);
  const effectiveConstraintId = hoveredConstraintId ?? lockedConstraintId;
  // Focus-reach view (plan/0103): the src/sink dipole SP-coloring for the effective
  // constraint — its constituent nodes glow signed, every other node fades to the
  // no-data fill. Separate from `reach` (the node-explorer click that opens the
  // DetailCard) so a hover just recolors nodes. Cached per constraint so sweeping
  // the list doesn't spam /map/reach; kept in sync with the effective id below.
  const [focusReach, setFocusReach] = useState<ConstraintReach | null>(null);
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
  }, [setConnState]);

  // Constraint overview load — once, independent of the playback window (the SF
  // structure is fixed per refit). Soft-fails to null (no overlay) on 503.
  useEffect(() => {
    fetchMapOverview(70, 6)
      .then((o) => setOverview(o))
      .catch(() => setOverview(null));
  }, []);

  useEffect(() => {
    fetchMapMeta()
      .then((m) => setMapMeta(m))
      .catch(() => setMapMeta(null));
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
    const spp = cur ? getErcotSppCached(cur) : null;
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
      totalLoadMw: spp?.total_load_mw ?? null,
      congestionAbsTotal: absTotal,
      modelNodes: model,
      ercotNodes: ercot,
    };
  }, [timestamps, currentIndex, spRows, forecastRows, forecastRunId]);

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
      setHoveredSp((current) => ({
        ...current,
        [side]: spId && props ? { spId, props, side, spState: spDecomp(spId) } : null,
      }));
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
  // True while the card's `reach` is a transient hover preview (an overview
  // popover row), so leaving the row clears it — but a *clicked* reach is not a
  // preview and survives (plan/0112).
  const previewReachRef = useRef(false);

  // Prediction-pane click: pin the node and trace its SF drivers (the overview /
  // reach machinery lives on this pane).
  const handleSpClickPrediction = useCallback(
    (spId: string, props: Record<string, unknown>) => {
      setReach(null); // a node click leaves constraint-reach mode
      reachReqRef.current++;
      // Also drop any locked/previewed constraint focus, so the overview marks
      // un-isolate instead of staying filtered to the prior constraint (plan/0112).
      previewReachRef.current = false;
      setLockedConstraintId(null);
      setHoveredConstraintId(null);
      setPinnedSp((current) => ({
        ...current,
        prediction: { spId, props, side: "prediction", spState: spDecomp(spId) },
      }));
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
      setPinnedSp((current) => ({
        ...current,
        actual: { spId, props, side: "actual", spState: spDecomp(spId) },
      }));
    },
    [spDecomp]
  );

  const handleClearPinnedSp = useCallback((side: "prediction" | "actual") => {
    setPinnedSp((current) => ({ ...current, [side]: null }));
    if (side !== "prediction") return;
    setExposures(null);
    setExposuresLoading(false);
    exposureReqRef.current++;
  }, []);

  // Constraint click (map marker or a driver row) → trace its reach; leaves the
  // node-explorer view. handleCloseReach / a background click return to normal.
  const handleConstraintClick = useCallback((constraintKey: string) => {
    setPinnedSp((current) => ({ ...current, prediction: null }));
    setExposures(null);
    exposureReqRef.current++;
    previewReachRef.current = false; // a clicked reach is locked, not a preview
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

  // ── Constraint focus (plan/0103, remodeled 0112) ────────────────────────────
  // Keep the focus-reach (node recolor) in sync with the EFFECTIVE constraint —
  // hovered when hovering, else the lock. Cached per constraint so sweeping the
  // panel doesn't spam /map/reach. This is the single source of node recoloring,
  // so hover previews and reverting to the lock both fall out of one effect.
  useEffect(() => {
    const id = effectiveConstraintId;
    if (!id) {
      // Invalidate any just-started hover request before restoring the normal
      // node view. Without this increment, a late response can reapply its old
      // constraint focus after the pointer has already left the row.
      focusReqRef.current++;
      setFocusReach(null);
      return;
    }
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
  }, [effectiveConstraintId]);

  // Hover a constraint (panel row or popover row): the transient overlay. Leaving
  // (id === null) reverts to whatever is locked — it never clears the lock.
  const handleConstraintHover = useCallback((id: string | null) => {
    setHoveredConstraintId(id);
  }, []);

  // Click a constraint: lock it. Clear the transient hover so the effective id
  // resolves to the lock immediately (and moving the mouse off doesn't reset it).
  const handleConstraintLock = useCallback((id: string) => {
    setLockedConstraintId(id);
    setHoveredConstraintId(null);
  }, []);

  const clearFocus = useCallback(() => {
    setLockedConstraintId(null);
    setHoveredConstraintId(null);
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

  // Overview node → DetailCard flow (plan/0112): a node dot rides the base `sps`
  // layer, so its hover/click already flow through handleSpHover /
  // handleSpClickPrediction — no overview-specific node handler needed.

  // Hover previews may recolor/isolate the map, but never replace a clicked card.
  // A transient reach card is allowed only while neither a node nor a constraint
  // card is locked; click remains the only action that changes the DetailCard.
  const handleConstraintPreview = useCallback((key: string | null) => {
    if (pinnedSp.prediction || (reach && !previewReachRef.current)) return;
    if (key == null) {
      if (previewReachRef.current) {
        previewReachRef.current = false;
        reachReqRef.current++;
        setReach(null);
      }
      return;
    }
    previewReachRef.current = true;
    const token = ++reachReqRef.current;
    fetchMapReach(key)
      .then((r) => {
        if (reachReqRef.current === token) setReach(r);
      })
      .catch(() => {
        if (reachReqRef.current === token) setReach(null);
      });
  }, [pinnedSp, reach]);

  // Background (empty-map) click clears whichever mode is active.
  const handlePredictionMapBackgroundClick = useCallback(() => {
    handleClearPinnedSp("prediction");
    handleCloseReach();
    clearFocus();
  }, [handleClearPinnedSp, handleCloseReach, clearFocus]);
  const handleActualMapBackgroundClick = useCallback(() => {
    handleClearPinnedSp("actual");
  }, [handleClearPinnedSp]);

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
    setPinnedSp((current) => {
      let changed = false;
      const next = { ...current };
      for (const side of ["prediction", "actual"] as const) {
        const card = current[side];
        if (!card) continue;
        const fresh = spDecomp(card.spId);
        const cur = card.spState;
        if (fresh.predicted !== cur?.predicted || fresh.market !== cur?.market ||
            fresh.error !== cur?.error || fresh.marketSpp !== cur?.marketSpp) {
          next[side] = { ...card, spState: fresh };
          changed = true;
        }
      }
      return changed ? next : current;
    });
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
            <Tooltip
              className="pane-badge__stat"
              tip="Settlement points (nodes) drawn on the map"
            >
              <span className="pane-badge__key">nodes</span>{" "}
              <b>{featCount.toLocaleString()}</b>
            </Tooltip>
            <Tooltip className="pane-badge__stat" tip={litHint}>
              <span className="pane-badge__key">{litNoun}</span>{" "}
              <b>{lit.toLocaleString()}</b>
            </Tooltip>
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
        onMapClick={handlePredictionMapBackgroundClick}
        selectedSpId={pinnedSp.prediction?.spId ?? null}
        side="prediction"
        onSpHover={handleSpHoverMain}
        onSpClick={handleSpClickPrediction}
        onMapReady={handleMainReady}
        showConstraints={showConstraints}
        reach={reach}
        overview={overview}
        isolatedConstraint={effectiveConstraintId}
        onIsolateConstraint={handleConstraintHover}
        onConstraintPreview={handleConstraintPreview}
        onConstraintSelect={handleConstraintSelectFromCard}
        focusReach={focusReach}
        ringedSpId={isMobile ? null : hoveredMemberSp}
        tapOnly={isMobile}
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
        hoveredSp={hoveredSp.prediction}
        pinnedSp={pinnedSp.prediction}
        exposures={exposures}
        exposuresLoading={exposuresLoading}
        reach={reach}
        onClose={() => handleClearPinnedSp("prediction")}
        onCloseReach={handleCloseReach}
        onSelectConstraint={handleConstraintSelectFromCard}
        onHoverConstraint={isMobile ? undefined : handleConstraintHover}
        onHoverMember={isMobile ? undefined : setHoveredMemberSp}
        onSelectMember={handleMemberSelect}
        mobile={isMobile}
      />
    </>
  );

  const rightPane = (
    <>
      <GridMap
        {...paneProps}
        side="actual"
        onMapClick={handleActualMapBackgroundClick}
        selectedSpId={pinnedSp.actual?.spId ?? null}
        onSpHover={handleSpHoverRight}
        onSpClick={handleSpClickActual}
        onMapReady={handleRightReady}
        tapOnly={isMobile}
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
        hoveredSp={hoveredSp.actual}
        pinnedSp={pinnedSp.actual}
        showDrivers={false}
        onClose={() => handleClearPinnedSp("actual")}
        mobile={isMobile}
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
        onMapClick={handlePredictionMapBackgroundClick}
        selectedSpId={pinnedSp.prediction?.spId ?? null}
        side="prediction"
        onSpHover={handleSpHoverMain}
        onSpClick={handleSpClickPrediction}
        onMapReady={handleMainReady}
        showConstraints={showConstraints}
        reach={reach}
        overview={overview}
        isolatedConstraint={effectiveConstraintId}
        onIsolateConstraint={handleConstraintHover}
        onConstraintPreview={handleConstraintPreview}
        onConstraintSelect={handleConstraintSelectFromCard}
        focusReach={focusReach}
        ringedSpId={isMobile ? null : hoveredMemberSp}
        congestionColor={forecastErrorColor}
        tapOnly={isMobile}
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
        barGradientOverride={forecastErrorGradientCss()}
        constraintOverlay={showConstraints && !!overview?.constraints.length}
        overviewTypes={showConstraints && !!overview?.constraints.length}
      />
      {/* Forecast-error card: the node's forecast / realized / error + SF drivers. */}
      <DetailCard
        hoveredSp={hoveredSp.prediction}
        pinnedSp={pinnedSp.prediction}
        exposures={exposures}
        exposuresLoading={exposuresLoading}
        reach={reach}
        onClose={() => handleClearPinnedSp("prediction")}
        onCloseReach={handleCloseReach}
        onSelectConstraint={handleConstraintSelectFromCard}
        onHoverConstraint={isMobile ? undefined : handleConstraintHover}
        onHoverMember={isMobile ? undefined : setHoveredMemberSp}
        onSelectMember={handleMemberSelect}
        mobile={isMobile}
      />
    </>
  );

  const sidePanelProps = {
    network: networkStats,
    headline,
    fitMeta: mapMeta,
    ranked,
    rankedLoading,
    constraintBasis,
    onConstraintBasis: setConstraintBasis,
    onSelectConstraint: handleConstraintLock,
    highlightedConstraintId: effectiveConstraintId,
    onHoverConstraint: isMobile ? undefined : handleConstraintHover,
    onMemberHover: isMobile ? undefined : setHoveredMemberSp,
  };
  const mobileLoadWindow = (
    <DateRangePicker
      inline
      onLoad={handleCustomLoadWindow}
      onSelectEvent={handleSelectEvent}
      events={CURATED_EVENTS}
      activeEventId={activeEventId}
      loading={loading}
    />
  );

  return (
    <>
      <Header
        activeWorkspace="map"
        onNavigate={onNavigate}
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
        mobileDrawerOpen={mobileDrawerOpen}
        onToggleMobileDrawer={() => setMobileDrawerOpen((open) => !open)}
      />

      <div className="app-workspace">
        {/* Forecast error = single map of P50 forecast − realized (default
            landing). Dual = prediction | ERCOT split, both under the active palette. */}
        {/* Map area 5 : side panel 2 → panel is ~2/7 (a bit under a third), wide
            enough that the constraint list/table don't wrap without overshooting. */}
        <div className="app-map-area">
          {renderedViewMode === "forecastError" ? (
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
        <SidePanel {...sidePanelProps} />
      </div>

      {isMobile && (
        <MobileDrawer
          open={mobileDrawerOpen}
          onClose={() => setMobileDrawerOpen(false)}
        >
          <section className="mobile-drawer__section">
            <div className="mobile-drawer__section-title label">Map</div>
            {overview?.constraints.length ? (
              <button
                className={showConstraints ? "active" : ""}
                onClick={() => setShowConstraints((shown) => !shown)}
              >
                Constraints overlay
              </button>
            ) : null}
          </section>
          <SidePanel
            {...sidePanelProps}
            variant="drawer"
            loadWindow={mobileLoadWindow}
          />
          <style>{`
            .mobile-drawer__section { margin-bottom: 18px; }
            .mobile-drawer__section-title {
              display: block;
              margin-bottom: 8px;
              color: var(--text-secondary);
            }
            .mobile-drawer__section > button { min-height: 38px; }
          `}</style>
        </MobileDrawer>
      )}

    </>
  );
}
