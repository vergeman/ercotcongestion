import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import type {
  SpRow,
  ExposuresResponse,
  ConstraintReach,
  RankedConstraints,
} from "../api/types";
import { formatCT } from "../lib/time";
import {
  forecastErrorColor,
  forecastErrorGradientCss,
} from "../lib/colors";
import Header from "../components/layout/Header";
import MobileDrawer from "../components/layout/MobileDrawer";
import CompareMap from "../components/map/CompareMap";
import DateRangePicker from "../components/playback/DateRangePicker";
import SidePanel from "../components/panels/SidePanel";
import { CURATED_EVENTS, type CuratedEvent } from "../lib/events";
import {
  type MapTarget,
} from "../lib/mapLinks";
import { useTheme } from "../lib/theme";
import { useExplorerSession } from "../hooks/useExplorerSession";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useMapBootstrap } from "../features/map/useMapBootstrap";
import { useMapRouteState } from "../features/map/MapRouteState";
import { useSynchronizedMaps } from "../features/map/useSynchronizedMaps";
import "../features/map/mapPresentation.css";
import { useConstraintSelection } from "../features/map/useConstraintSelection";
import { useMapCursorData } from "../features/map/useMapCursorData";
import { useMapScorecard } from "../features/map/useMapScorecard";
import { useMapViewControls } from "../features/map/useMapViewControls";
import { PredictionPane } from "../features/map/PredictionPane";
import { MarketPane } from "../features/map/MarketPane";
import type {
  PaneSide,
  PaneSp,
  PredictionInteractions,
  MarketInteractions,
  PredictionPaneConfig,
} from "../features/map/mapPaneTypes";

const MOBILE_BREAKPOINT = "(max-width: 767px)";

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
  const {
    view, setView, dataMode, setDataMode, target, selectTarget,
  } = useMapRouteState({ search: routeSearch, onChange: onSelectionRouteChange });
  const [targetUnavailable, setTargetUnavailable] = useState(false);
  const handledTargetRef = useRef<string | null>(null);
  // Two orthogonal axes (0130). `view` picks the layout: `forecast` (default
  // landing) is a single map of the model's deterministic prediction; `market` is a
  // single map of ERCOT's realized DAM values; `compare` is the prediction |
  // ERCOT split; `error` is a single map of forecast − realized congestion.
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
  // View/data-mode transition rules (constraint-overlay defaults, Error's
  // congestion lock and restore) live in one hook; mobile still renders Forecast.
  const {
    renderedView, showConstraints, setShowConstraints, handleView, handleDataMode,
  } = useMapViewControls({ view, setView, dataMode, setDataMode, isMobile });

  // Mirror view/dataMode into the URL (0131), the same read/write-through-the-
  // URL convention the constraint/sp selection already follows. Fires for both
  // a manual Header click and the no-settled-data downgrade effect further
  // below — whatever changed the local axis — and carries the current
  // selection forward explicitly (App's `withCoord` only fills in the shared
  // coordinate, not constraint/sp, so a selection would otherwise be dropped
  // by a view-only change). Guarded against the URL already agreeing, so it
  // doesn't fire redundantly on mount or fight an inbound deep link.
  const {
    timestamps, currentIndex, loading, connectionState: connState,
    setConnectionState: setConnState, lastUpdated, activeEventId,
    congestionStats, sppStats, forecastCongestionStats, forecastLmpStats,
    errorStats, forecastRunId, selectEvent,
    loadCustomWindow: handleCustomLoadWindow,
  } = session;
  const handleSelectEvent = useCallback(
    (event: CuratedEvent) => selectEvent(event, setDataMode),
    [selectEvent, setDataMode]
  );
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);

  // Each map owns its own card interaction. In dual view, touching the ERCOT
  // pane must not replace or close the prediction pane's card (and vice versa).
  const [hoveredSp, setHoveredSp] = useState<Record<PaneSide, PaneSp | null>>({
    prediction: null,
    actual: null,
  });
  const [pinnedSp, setPinnedSp] = useState<Record<PaneSide, PaneSp | null>>({
    prediction: null,
    actual: null,
  });

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
  // DetailCard) so a hover just recolors nodes. Cached per constraint AND CT
  // delivery day so sweeping the list doesn't spam /map/reach while moving the
  // scrubber across days still refetches (0144); kept in sync with the effective
  // id below.
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
  const { topology, topologyReady, overview } = useMapBootstrap(setConnState);
  const { loadRanked, loadExposures: requestExposures, loadReach } = useConstraintSelection();

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

  const { onMainReady: handleMainReady, onRightReady: handleRightReady } = useSynchronizedMaps();

  // Everything the cursor derives for the panes and side panel: the CT delivery
  // day (undefined before a window loads → server defaults to the latest built
  // day), the cursor instant (`t` for /map/exposures and /map/reach), preview
  // status, this hour's rows, forecast-error rows, conditions, network stats,
  // and the per-SP decomposition.
  const {
    cursorTs, deliveryDay, isPreviewDay, spRows, forecastRows, lambdaSource,
    errorRows, conditionsStats, networkStats, spDecomp,
  } = useMapCursorData(timestamps, currentIndex, forecastRunId);
  const scorecard = useMapScorecard(deliveryDay, forecastRunId);

  // focusReachCache key: a cached dipole belongs to one constraint on one CT
  // delivery day, never to the constraint alone.
  const focusReachKey = useCallback(
    (id: string) => `${deliveryDay ?? "latest"}|${id}`,
    [deliveryDay]
  );

  // Ranked constraints are scoped to the delivery day and basis. Cancellation
  // replaces the prior request-id guard, so a scrub can never publish an old day.
  useEffect(() => {
    const controller = new AbortController();
    setRankedLoading(true);
    loadRanked(constraintBasis, deliveryDay, 30, controller.signal)
      .then((r) => {
        if (!controller.signal.aborted) setRanked(r);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted && !(error instanceof DOMException && error.name === "AbortError")) setRanked(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) setRankedLoading(false);
      });
    return () => controller.abort();
  }, [deliveryDay, constraintBasis, loadRanked]);

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
    selectTarget(target);
  }, [selectTarget]);

  // Prediction-pane click: pin the node and trace its SF drivers (the overview /
  // One place the driver list is requested from, so the click path, the basis
  // toggle and the scrubber cannot fetch it differently. The token guard drops
  // responses from a superseded request — all three race, and scrubbing fires
  // one per hour tick.
  //
  // Fetch only — it never sets state synchronously, so the effect below can
  // call it without cascading a render. Clearing the previous list is the
  // caller's job, and only click and basis-toggle do it: there the old list is
  // about to become wrong. Scrubbing leaves it up until the new one lands,
  // since the node is unchanged and blanking on every hour tick would strobe.
  const loadExposures = useCallback(
    (spId: string) => {
      const token = ++exposureReqRef.current;
      requestExposures(spId, cursorTs)
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
    [cursorTs, requestExposures]
  );

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
      // The load itself is the effect's job (it also owns cursor changes), so
      // this only clears the outgoing node's drivers.
      setExposures(null);
      setExposuresLoading(true);
      exposureReqRef.current++;
    },
    [spDecomp, setSelectionRoute]
  );

  const pinnedPredictionSp = pinnedSp.prediction?.spId;

  // The pinned node's drivers follow the scrubber. Every value in the response
  // is specific to the cursor's CT delivery day and hour (0144/0145) — mu and
  // the contribution ranking — so a card left on the hour it was opened at
  // silently disagrees with the map under it. Keyed on the hour and the node,
  // both of which change the request.
  useEffect(() => {
    if (!pinnedPredictionSp) return;
    loadExposures(pinnedPredictionSp);
  }, [pinnedPredictionSp, loadExposures]);

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
    loadReach(constraintKey, cursorTs)
      .then((r) => {
        if (reachReqRef.current === token) setReach(r);
      })
      .catch(() => {
        if (reachReqRef.current === token) setReach(null);
      });
  }, [setSelectionRoute, cursorTs, loadReach]);

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

    // Wait for the scrubber to resolve the cursor before replaying. The URL
    // carries the coordinate, but `timestamps` fills in asynchronously — and
    // this workspace stays mounted on the Matrix route (App.tsx), so a Matrix
    // deep link replays the target here while the map's own window is still
    // loading. Firing then sends the click fetches with no `t`, which serves the
    // latest built day instead of the linked one, and `handledTargetRef` below
    // would mark the target done and suppress the corrected refetch. `cursorTs`
    // is a dependency, so the effect re-runs once the cursor arrives.
    if (!cursorTs) return;

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
    loadReach(target.value, cursorTs)
      .then((nextReach) => {
        if (reachReqRef.current !== token) return;
        if (!nextReach?.available) {
          setReach(null);
          setLockedConstraintId(null);
          setTargetUnavailable(true);
          return;
        }
        setReach(nextReach);
        focusReachCache.current.set(focusReachKey(target.value), nextReach);
        setLockedConstraintId(target.value);
      })
      .catch(() => {
        if (reachReqRef.current !== token) return;
        setReach(null);
        setLockedConstraintId(null);
        setTargetUnavailable(true);
      });
  }, [target, topologyReady, spPoints, handleSpClickPrediction, cursorTs, focusReachKey, loadReach]);

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
    const cached = focusReachCache.current.get(focusReachKey(id));
    if (cached) {
      setFocusReach(cached);
      return;
    }
    const token = ++focusReqRef.current;
    loadReach(id, cursorTs)
      .then((r) => {
        if (r) focusReachCache.current.set(focusReachKey(id), r);
        if (focusReqRef.current === token) setFocusReach(r);
      })
      .catch(() => {
        if (focusReqRef.current === token) setFocusReach(null);
      });
  }, [effectiveConstraintId, cursorTs, focusReachKey, loadReach]);

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

  // Constraint selection from either a DetailCard driver row or the Constraints
  // tab: load its member list into the constraint card AND lock map isolation, so
  // the isolated view persists after the pointer leaves — until a background
  // click or another selection. Both entry points deliberately share this
  // composite route + reach + lock behavior.
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
    loadReach(key, cursorTs)
      .then((r) => {
        if (reachReqRef.current === token) setReach(r);
      })
      .catch(() => {
        if (reachReqRef.current === token) setReach(null);
      });
  }, [pinnedSp, reach, cursorTs, loadReach]);

  // Background (empty-map) click clears whichever mode is active.
  const handlePredictionMapBackgroundClick = useCallback(() => {
    handleClearPinnedSp("prediction");
    handleCloseReach();
    clearFocus();
  }, [handleClearPinnedSp, handleCloseReach, clearFocus]);
  const handleActualMapBackgroundClick = useCallback(() => {
    handleClearPinnedSp("actual");
  }, [handleClearPinnedSp]);

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
  const badgeProps = { cursorLabel, nodeCount: featCount, emptyTopology: spTopologyEmpty };

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

  // Prediction-side state + callbacks, shared by the Forecast and Error panes so
  // both carry the decomposition and SF drivers. Ownership stays here.
  const predictionInteractions: PredictionInteractions = {
    hoveredSp: hoveredSp.prediction,
    pinnedSp: pinnedSp.prediction,
    reach,
    focusReach,
    effectiveConstraintId,
    exposures,
    exposuresLoading,
    hoveredMemberSp,
    onMapBackgroundClick: handlePredictionMapBackgroundClick,
    onSpHover: handleSpHoverMain,
    onSpClick: handleSpClickPrediction,
    onMapReady: handleMainReady,
    onIsolateConstraint: handleConstraintHover,
    onConstraintPreview: handleConstraintPreview,
    onConstraintSelect: handleConstraintSelectFromCard,
    onClearPinned: () => handleClearPinnedSp("prediction"),
    onCloseReach: handleCloseReach,
    onHoverConstraint: handleConstraintHover,
    onHoverMember: setHoveredMemberSp,
    onSelectMember: handleMemberSelect,
  };
  const marketInteractions: MarketInteractions = {
    hoveredSp: hoveredSp.actual,
    pinnedSp: pinnedSp.actual,
    onMapBackgroundClick: handleActualMapBackgroundClick,
    onSpHover: handleSpHoverRight,
    onSpClick: handleSpClickActual,
    onMapReady: handleRightReady,
    onClearPinned: () => handleClearPinnedSp("actual"),
  };

  const forecastConfig: PredictionPaneConfig = {
    view: "forecast",
    rows: leftRows,
    lmpStats: leftLmpStats,
    mcStats: leftMcStats,
    dataMode,
    label: predictionLabel,
    litCount: litFor(leftRows),
    litNoun: "forecast",
    litHint: "Nodes the model forecasts a value for at this hour (colored on the map). The model covers its full nodal universe — including resource nodes (RN / CC / PUN) that ERCOT publishes no settlement price for — so this exceeds the ERCOT priced count.",
    lambdaIndicative,
    previewBadge: isPreviewDay,
  };

  // Forecast-error view: forecast − realized congestion on the diverging palette
  // (forced congestion, error-anchored stats). Uses the same prediction pane, so
  // the card carries the decomposition + SF drivers just like the dual left pane.
  const errorLit = errorRows.filter((r) => r.congestion != null).length;
  const errorLabel =
    hasForecast && forecastRunId
      ? "Forecast Error: Prediction Model − ERCOT DAM"
      : "Forecast Error: no forecast this window";
  const errorConfig: PredictionPaneConfig = {
    view: "error",
    rows: errorRows,
    lmpStats: null,
    mcStats: errorStats,
    dataMode: "congestion",
    congestionColor: forecastErrorColor,
    label: errorLabel,
    litCount: errorLit,
    litNoun: "compared",
    litHint: "Nodes with both a model forecast and a realized value, so an error is defined",
    titleOverride: "Congestion Forecast Error · Forecast − Realized ($/MWh)",
    signLabels: { neg: "Under", pos: "Over" },
    barGradientOverride: forecastErrorGradientCss(),
  };

  const sharedPaneProps = {
    points: spPoints,
    overview,
    showConstraints,
    constraintsToggle,
    cursorTs,
    badge: badgeProps,
    isMobile,
  };

  const forecastPane = (
    <PredictionPane config={forecastConfig} interactions={predictionInteractions} {...sharedPaneProps} />
  );
  const marketPane = (
    <MarketPane
      interactions={marketInteractions}
      points={spPoints}
      rows={spRows}
      dataMode={dataMode}
      lmpStats={sppStats}
      mcStats={congestionStats}
      litCount={litCount}
      badge={badgeProps}
      isMobile={isMobile}
    />
  );
  const errorPane = (
    <PredictionPane config={errorConfig} interactions={predictionInteractions} {...sharedPaneProps} />
  );

  const sidePanelProps = {
    network: networkStats,
    conditions: conditionsStats,
    mapView: renderedView,
    // Keep the last good scorecard mounted while the next day's fetch is in
    // flight, so scrub/playback swaps the numbers in place — the section never
    // unmounts and there's no flash.
    scorecard,
    fitMeta: scorecard?.fit_metadata ?? null,
    ranked,
    rankedLoading,
    constraintBasis,
    onConstraintBasis: setConstraintBasis,
    onSelectConstraint: handleConstraintSelectFromCard,
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
