import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import type maplibregl from "maplibre-gl";
import type {
  SpRow,
  MapDataMode,
  MapView,
  ExposuresResponse,
  ConstraintReach,
  MapOverview,
  MapMeta,
  RankedConstraints,
  ScoreboardHeadline,
  ConditionsEntry,
} from "../api/types";
import {
  fetchMapSummary,
  fetchMapExposures,
  fetchMapReach,
  fetchMapConstraintsRanked,
} from "../api/client";
import { formatCT } from "../lib/time";
import {
  getErcotCached,
  getErcotSppCached,
  getForecastCached,
  getForecastHorizon,
  getConditionsCached,
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
import {
  type MapTarget,
  parseMapTarget,
  mapTargetSearch,
  parseMapViewState,
  mapViewStateParams,
} from "../lib/mapLinks";
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
    predictedSpp: number | null;
  } | null;
}

export interface MapWorkspaceProps {
  session: ReturnType<typeof useExplorerSession>;
  onNavigate: (workspace: "map" | "matrix") => void;
  routeSearch: string;
  onSelectionRouteChange: (search: string) => void;
}

// The map's selection convention (the `MapTarget` shape, parse + serialize, and
// the two `?…=` param names) is single-sourced in lib/mapLinks so other pages
// can build deep links into the map that match exactly what a click here writes.

export default function MapWorkspace({ session, onNavigate, routeSearch, onSelectionRouteChange }: MapWorkspaceProps) {
  // Mobile is intentionally a map-first experience. Keep the user's desktop
  // view choice in state, but never mount the second synchronized map below the
  // breakpoint; returning to desktop restores their chosen view.
  const isMobile = useMediaQuery(MOBILE_BREAKPOINT);
  // Re-render on theme flip so the forecast-error legend gradient (built from the
  // theme-aware palette) stays in sync with the map fills.
  useTheme();
  const [topology, setTopology] = useState<unknown | null>(null);
  const [topologyReady, setTopologyReady] = useState(false);
  const target = useMemo(() => parseMapTarget(routeSearch), [routeSearch]);
  const [targetUnavailable, setTargetUnavailable] = useState(false);
  const handledTargetRef = useRef<string | null>(null);
  // Two orthogonal axes (0130). `view` picks the layout: `forecast` (default
  // landing) is a single map of the model's own P50 prediction; `market` is a
  // single map of ERCOT's realized DAM values; `compare` is the prediction |
  // ERCOT split; `error` is a single map of P50 forecast − realized congestion.
  // `dataMode` picks the ERCOT quantity a single/compare pane colors by; `error`
  // is congestion-based regardless (forced below). Mobile is forced-single and
  // always resolves to the Forecast layout, following whichever `dataMode` is
  // active — never `market`/`compare`/`error` (no room for two panes, and the
  // realized-only/error layouts read the operator's own vantage, not a
  // reader's).
  // Seeded from the URL (0131): a deep link (the Brief hero, a shared /map
  // link) lands directly on the requested view/data rather than always
  // opening on the shipped default and reconciling after. `parseMapViewState`
  // already canonicalizes (unknown/missing → Forecast × Congestion, Error →
  // congestion), so this is never an unreachable combination.
  const [view, setView] = useState<MapView>(() => parseMapViewState(routeSearch).view);
  const renderedView: MapView = isMobile ? "forecast" : view;
  const [dataMode, setDataMode] = useState<MapDataMode>(() => parseMapViewState(routeSearch).data);
  // Data selection held from before entering Error, so leaving it restores
  // rather than defaulting back to congestion.
  const prevDataModeRef = useRef<MapDataMode>("congestion");

  // Mirror view/dataMode into the URL (0131), the same read/write-through-the-
  // URL convention the constraint/sp selection already follows. Fires for both
  // a manual Header click and the no-settled-data downgrade effect further
  // below — whatever changed the local axis — and carries the current
  // selection forward explicitly (App's `withCoord` only fills in the shared
  // coordinate, not constraint/sp, so a selection would otherwise be dropped
  // by a view-only change). Guarded against the URL already agreeing, so it
  // doesn't fire redundantly on mount or fight an inbound deep link.
  useEffect(() => {
    const current = parseMapViewState(routeSearch);
    if (current.view === view && current.data === dataMode) return;
    const params = mapViewStateParams({ view, data: dataMode });
    if (target) params.set(target.kind, target.value);
    onSelectionRouteChange(`?${params.toString()}`);
    // Only the axes themselves should trigger a push; routeSearch/target
    // reflect the URL this effect writes to and reading them here isn't a
    // signal to re-run.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, dataMode]);
  const {
    timestamps, currentIndex, loading, connectionState: connState,
    setConnectionState: setConnState, lastUpdated, activeEventId,
    congestionStats, sppStats, forecastCongestionStats, forecastLmpStats,
    errorStats, forecastRunId, selectEvent,
    loadCustomWindow: handleCustomLoadWindow,
  } = session;
  const handleSelectEvent = useCallback(
    (event: CuratedEvent) => selectEvent(event, setDataMode),
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
  // the stats cover the cursor's delivery day so coloring is stable within it;
  // `forecastRunId` labels which refit is serving (null → no forecast covered
  // the window, pane falls back to the realized rows).
  const [forecastRows, setForecastRows] = useState<SpRow[]>([]);
  // Forecast-error (P50 forecast − realized congestion) delivery-day stats, for
  // the diverging palette centered at 0 in the forecast-error view. The per-hour
  // error rows are derived below.
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

  // One bundled load-time request (0137): topology, the constraint overview,
  // the SF-refit meta, and the scorecard headline all load together, once,
  // independent of the playback window (each is fixed per refit / static).
  // overview/meta/headline are independently null on their own soft-fail
  // (nothing built/loaded for that section yet); topology failing is still
  // the harder error it always was (connection state flips to "error").
  useEffect(() => {
    fetchMapSummary()
      .then((b) => {
        setTopology(b.topology);
        setConnState("ok");
        setOverview(b.overview);
        setMapMeta(b.meta);
        setHeadline(b.headline);
      })
      .catch(() => setConnState("error"))
      .finally(() => setTopologyReady(true));
  }, [setConnState]);

  // The cursor's CT delivery day — the day the `Constraints` tab ranks. Derived
  // from the current frame's Central date (ERCOT operates on Central), so the
  // ranking follows the map's day. Undefined before a window loads → the server
  // defaults to the forecast run's latest built day.
  const deliveryDay = useMemo<string | undefined>(() => {
    const ts = timestamps[currentIndex];
    return ts ? formatCT(ts, "yyyy-MM-dd") : undefined;
  }, [timestamps, currentIndex]);

  // Whether the cursor's forecast day is a PREVIEW (horizon 2, 0123) — read-only
  // off the per-day provenance the range response carried, keyed by the frame's UTC
  // date (the backend's delivery_date). No toggle, no extra fetch: the scrubber
  // still renders the one coalesced series; this only labels which days are still
  // previews. Recomputed as the cursor moves or a new window loads.
  const isPreviewDay = useMemo<boolean>(() => {
    const ts = timestamps[currentIndex];
    return ts ? getForecastHorizon(ts) === 2 : false;
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
  // same scrubber index as the realized rows above. `lambdaSource` (0130) tracks
  // whether that λ was a settled DAM value or the persistence fallback, so the
  // LMP legend/hover can mark a persisted hour's price as indicative — display
  // only, never a graded signal.
  const [lambdaSource, setLambdaSource] = useState<"settled" | "persisted" | null>(null);
  useEffect(() => {
    if (!timestamps.length) {
      setForecastRows([]);
      setLambdaSource(null);
      return;
    }
    const fc = getForecastCached(timestamps[currentIndex]);
    if (!fc) {
      setForecastRows([]);
      setLambdaSource(null);
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
    setLambdaSource(fc.lambda_source);
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
  // Total Load lives in the Conditions panel's Load by Region row now, not here.
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

  // Load / Wind / Solar / Outages (plan/0141): the same cursor hour as
  // `networkStats`, read from its own soft-fail cache. `undefined` (no cache
  // entry for this hour) collapses to `null` so SidePanel's null-dash rendering
  // handles it the same way as every other stat.
  const conditionsStats = useMemo<ConditionsEntry | null>(() => {
    const cur = timestamps[currentIndex] ?? null;
    return (cur ? getConditionsCached(cur) : null) ?? null;
  }, [timestamps, currentIndex]);

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
      return {
        predicted,
        market,
        error,
        marketSpp: m?.spp ?? null,
        predictedSpp: f?.spp ?? null,
      };
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
  const setSelectionRoute = useCallback((target: MapTarget) => {
    handledTargetRef.current = `${target.kind}:${target.value}`;
    setTargetUnavailable(false);
    onSelectionRouteChange(mapTargetSearch(target));
  }, [onSelectionRouteChange]);

  // Prediction-pane click: pin the node and trace its SF drivers (the overview /
  // reach machinery lives on this pane).
  const handleSpClickPrediction = useCallback(
    (spId: string, props: Record<string, unknown>, writeRoute = true) => {
      if (writeRoute) setSelectionRoute({ kind: "sp", value: spId });
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
    [spDecomp, setSelectionRoute]
  );

  // Actual-pane click: pin the node scoped to the realized values only — no SF
  // drivers (those belong to the prediction pane), so drop any in-flight fetch.
  const handleSpClickActual = useCallback(
    (spId: string, props: Record<string, unknown>) => {
      setSelectionRoute({ kind: "sp", value: spId });
      setPinnedSp((current) => ({
        ...current,
        actual: { spId, props, side: "actual", spState: spDecomp(spId) },
      }));
    },
    [spDecomp, setSelectionRoute]
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
  const handleConstraintClick = useCallback((constraintKey: string, writeRoute = true) => {
    if (writeRoute) setSelectionRoute({ kind: "constraint", value: constraintKey });
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
  }, [setSelectionRoute]);

  // Deep links from the Matrix retain the requested identifier in the URL and
  // replay the equivalent Map selection once its representation is available.
  // The map fetches are selection work, not inspector metadata lookups.
  useEffect(() => {
    if (!target) {
      handledTargetRef.current = null;
      setTargetUnavailable(false);
      return;
    }
    const key = `${target.kind}:${target.value}`;
    if (handledTargetRef.current === key) return;

    if (target.kind === "sp") {
      if (!topologyReady) return;
      handledTargetRef.current = key;
      const feature = spPoints?.features.find((point) =>
        (point.properties?.sp_id as string | undefined) === target.value
      );
      if (!feature) {
        setTargetUnavailable(true);
        return;
      }
      setTargetUnavailable(false);
      handleSpClickPrediction(target.value, (feature.properties ?? { sp_id: target.value }) as Record<string, unknown>, false);
      return;
    }

    handledTargetRef.current = key;
    setTargetUnavailable(false);
    setPinnedSp((current) => ({ ...current, prediction: null }));
    setExposures(null);
    exposureReqRef.current++;
    previewReachRef.current = false;
    setHoveredConstraintId(null);
    const token = ++reachReqRef.current;
    fetchMapReach(target.value)
      .then((nextReach) => {
        if (reachReqRef.current !== token) return;
        if (!nextReach?.available) {
          setReach(null);
          setLockedConstraintId(null);
          setTargetUnavailable(true);
          return;
        }
        setReach(nextReach);
        focusReachCache.current.set(target.value, nextReach);
        setLockedConstraintId(target.value);
      })
      .catch(() => {
        if (reachReqRef.current !== token) return;
        setReach(null);
        setLockedConstraintId(null);
        setTargetUnavailable(true);
      });
  }, [target, topologyReady, spPoints, handleSpClickPrediction]);

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
  const handleConstraintLock = useCallback((id: string, writeRoute = true) => {
    if (writeRoute) setSelectionRoute({ kind: "constraint", value: id });
    setLockedConstraintId(id);
    setHoveredConstraintId(null);
  }, [setSelectionRoute]);

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
      handleConstraintLock(key, false);
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

  // Market/Compare/Error require settled data in the loaded window (0130); a
  // pure-forecast window (nothing has settled yet) gates them off. Read off the
  // cursor's delivery-day realized stats already computed by the session.
  const hasSettledData = congestionStats != null;

  // Switch the view axis, applying that view's SF-overlay default: on in
  // Forecast and Error (the overlay is that view's own mechanism), off in
  // Compare (a per-pane explainer) and Market (no overlay at all). The manual
  // overlay toggle then persists until the next view switch. Entering Error
  // locks the data axis to congestion, remembering whatever was active so
  // leaving it restores rather than defaulting back.
  const handleView = useCallback((v: MapView) => {
    if (v === "error" && view !== "error") {
      prevDataModeRef.current = dataMode;
      setDataMode("congestion");
    } else if (v !== "error" && view === "error") {
      setDataMode(prevDataModeRef.current);
    }
    setView(v);
    setShowConstraints(v === "forecast" || v === "error");
  }, [view, dataMode]);

  const handleDataMode = useCallback((d: MapDataMode) => {
    if (view === "error") return; // locked; the Header disables the chip too
    setDataMode(d);
  }, [view]);

  // Scrubbing into a pre-market window while sitting in a settled-only view
  // (Market/Compare/Error) leaves nothing to render on at least one pane —
  // downgrade to Forecast, the one view that's always available, mirroring the
  // Header's own disabled-chip rule rather than stranding a broken layout.
  useEffect(() => {
    if (hasSettledData || view === "forecast") return;
    if (view === "error") setDataMode(prevDataModeRef.current);
    setView("forecast");
    setShowConstraints(true);
  }, [hasSettledData, view]);

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
  // Color the forecast on the realized day's scale when both exist, so the two
  // panes are directly comparable; fall back to the forecast's own daily scale
  // on a forecast-only window (tomorrow, no realized rows yet).
  const leftMcStats = congestionStats ?? forecastCongestionStats;
  const leftLmpStats = sppStats ?? forecastLmpStats;

  const litFor = (rows: SpRow[]) =>
    rows.filter((r) => (dataMode === "lmp" ? r.spp != null : r.congestion != null))
      .length;
  const litCount = litFor(spRows);
  // The cursor hour, formatted once for every pane badge's coordinate line —
  // "view · data · timestamp" (0130), a first-class label so a reader always
  // knows what a pane shows without cross-referencing the header.
  const cursorLabel = timestamps[currentIndex]
    ? `${formatCT(timestamps[currentIndex], "MMM d, HH:mm")} CT`
    : "—";
  const VIEW_LABELS: Record<MapView, string> = {
    forecast: "Forecast",
    market: "Market",
    compare: "Compare",
    error: "Error",
  };
  const DATA_LABELS: Record<MapDataMode, string> = {
    congestion: "Congestion",
    lmp: "Price (LMP)",
  };

  // The pane subtitle. A bold title line names what the pane shows; a coord
  // line pins it to view · data · timestamp; the meta row reports node coverage
  // in words — `litNoun` says what "having a value" means for this pane
  // (forecast / priced / compared) so the count reads plainly.
  const badgeFor = (
    label: string,
    paneView: MapView,
    paneDataMode: MapDataMode,
    lit: number = litCount,
    litNoun = "priced",
    litHint = "Nodes with a value at this hour (colored on the map); the rest are drawn unlit"
  ) => (
    <>
      <span className="pane-badge__title">{label}</span>
      <span className="pane-badge__coord mono">
        {VIEW_LABELS[paneView]} · {DATA_LABELS[paneDataMode]} · {cursorLabel}
      </span>
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
    dataMode,
    lmpStats: sppStats,
    mcStats: congestionStats,
  };

  // The forecast pane's label: which refit is serving + the served day (the
  // cursor hour's date), or the realized fallback.
  const predictionLabel =
    hasForecast && forecastRunId
      ? `Prediction Model: forecast ${forecastRunId}`
      : "Prediction Model: no forecast this window";

  // The constraints-overlay control (0130): lives in the legend of every pane
  // that draws forecast data (Forecast/Compare's prediction pane, Error) —
  // never Market. Hidden until the overview has actually loaded, matching the
  // old header control's own hidden-until-loaded rule.
  const constraintsToggle = overview?.constraints.length
    ? { checked: showConstraints, onChange: setShowConstraints }
    : undefined;
  // Persistence-λ provenance (0130): a property of the cursor hour, not the
  // active view — the DetailCard's Predicted LMP row is part of the full
  // decomposition shown in every view, so this stays independent of `dataMode`.
  // Legend gates its own "Indicative" note on the LMP palette internally.
  const lambdaIndicative = lambdaSource === "persisted";

  const forecastPane = (
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
          "forecast",
          dataMode,
          litFor(leftRows),
          "forecast",
          "Nodes the model forecasts a value for at this hour (colored on the map). The model covers its full nodal universe — including resource nodes (RN / CC / PUN) that ERCOT publishes no settlement price for — so this exceeds the ERCOT priced count."
        )}
        {isPreviewDay && (
          <span className="pane-badge__preview" role="status">
            Preview — refreshes at noon CT
          </span>
        )}
      </div>
      <Legend
        dataMode={dataMode}
        rows={leftRows}
        lmpStats={leftLmpStats}
        mcStats={leftMcStats}
        constraintOverlay={showConstraints && !!overview?.constraints.length}
        overviewTypes={showConstraints && !!overview?.constraints.length}
        constraintsToggle={constraintsToggle}
        lambdaIndicative={lambdaIndicative}
      />
      {/* Prediction card: the node's forecast readout + its SF drivers. */}
      <DetailCard
        hoveredSp={hoveredSp.prediction}
        pinnedSp={pinnedSp.prediction}
        lambdaIndicative={lambdaIndicative}
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

  const marketPane = (
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
          "market",
          dataMode,
          litCount,
          "priced",
          "Nodes with a published ERCOT DAM settlement price (SPP) at this hour (colored on the map). Resource nodes (RN / CC / PUN) carry no published price, so this is fewer than the model's forecast count."
        )}
      </div>
      <Legend
        dataMode={dataMode}
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
        dataMode="congestion"
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
          "error",
          "congestion",
          errorLit,
          "compared",
          "Nodes with both a model forecast and a realized value, so an error is defined"
        )}
      </div>
      <Legend
        dataMode="congestion"
        rows={errorRows}
        lmpStats={null}
        mcStats={errorStats}
        titleOverride="Congestion Forecast Error · Forecast − Realized ($/MWh)"
        signLabels={{ neg: "Under", pos: "Over" }}
        barGradientOverride={forecastErrorGradientCss()}
        constraintOverlay={showConstraints && !!overview?.constraints.length}
        overviewTypes={showConstraints && !!overview?.constraints.length}
        constraintsToggle={constraintsToggle}
      />
      {/* Forecast-error card: the node's forecast / realized / error + SF drivers. */}
      <DetailCard
        hoveredSp={hoveredSp.prediction}
        pinnedSp={pinnedSp.prediction}
        lambdaIndicative={lambdaIndicative}
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
    conditions: conditionsStats,
    mapView: renderedView,
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
        view={view}
        onView={handleView}
        dataMode={dataMode}
        onDataMode={handleDataMode}
        marketAvailable={hasSettledData}
        lastUpdated={lastUpdated}
        connectionState={connState}
        mobileDrawerOpen={mobileDrawerOpen}
        onToggleMobileDrawer={() => setMobileDrawerOpen((open) => !open)}
      />

      <div className="app-workspace">
        {/* Forecast/Market/Error = a single map; Compare = the prediction | ERCOT
            split. All render under the active `dataMode` (Error forces congestion). */}
        {/* Map area 5 : side panel 2 → panel is ~2/7 (a bit under a third), wide
            enough that the constraint list/table don't wrap without overshooting. */}
        <div className="app-map-area">
          {targetUnavailable && target && (
            <div className="map-target-notice" role="status">
              Requested {target.kind === "sp" ? "settlement point" : "constraint"} <span className="mono">{target.value}</span> is not present in this map fit/window.
            </div>
          )}
          {renderedView === "compare" ? (
            <CompareMap main={forecastPane} right={marketPane} />
          ) : (
            <div className="map-view-single">
              {renderedView === "market"
                ? marketPane
                : renderedView === "error"
                ? errorPane
                : forecastPane}
            </div>
          )}
          <style>{`
            .map-view-single {
              width: 100%;
              height: 100%;
              position: relative;
            }
            .map-target-notice {
              background: var(--bg-panel);
              border: 1px solid var(--warning, #f59e0b);
              color: var(--text-primary);
              font-size: var(--fs-label);
              left: 10px;
              max-width: min(440px, calc(100% - 20px));
              padding: 8px 10px;
              position: absolute;
              top: 68px;
              z-index: 3;
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
            .pane-badge__coord {
              font-size: var(--fs-label);
              color: var(--text-muted);
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
            /* Preview provenance (0123): the served day is a t+2 preview, refreshed
               by the noon-CT final run. A static, sentence-case label (the app's
               casing rule) carrying the shared --track-label token; the accent
               border/color sets it apart from the neutral title/meta above (reusing
               the app-wide --accent so it tracks both themes). */
            .pane-badge__preview {
              align-self: flex-start;
              margin-top: 2px;
              padding: 1px 6px;
              border: 1px solid var(--accent);
              border-radius: 3px;
              font-family: var(--font-label);
              font-weight: var(--fw-label);
              font-size: var(--fs-body);
              letter-spacing: var(--track-label);
              color: var(--accent);
            }
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
          {/* The constraints-overlay control lives in the forecast pane's own
              Legend (0130) — mobile is forced-single onto that pane, so it's
              already on screen; no duplicate control needed here. */}
          <SidePanel
            {...sidePanelProps}
            variant="drawer"
            loadWindow={mobileLoadWindow}
          />
        </MobileDrawer>
      )}

    </>
  );
}
