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
import { MapPane } from "../features/map/MapPane";
import type {
  PaneSide,
  PaneSp,
  MapPaneInteractions,
  MapPaneConfig,
} from "../features/map/mapPaneTypes";

const MOBILE_BREAKPOINT = "(max-width: 767px)";

export interface MapWorkspaceProps {
  session: ReturnType<typeof useExplorerSession>;
  onNavigate: (workspace: "map" | "matrix") => void;
  routeSearch: string;
  onSelectionRouteChange: (search: string) => void;
}

export default function MapWorkspace({ session, onNavigate, routeSearch, onSelectionRouteChange }: MapWorkspaceProps) {
  const isMobile = useMediaQuery(MOBILE_BREAKPOINT);
  useTheme();
  const {
    view, setView, dataMode, setDataMode, target, selectTarget,
  } = useMapRouteState({ search: routeSearch, onChange: onSelectionRouteChange });
  const [targetUnavailable, setTargetUnavailable] = useState(false);
  const handledTargetRef = useRef<string | null>(null);
  const {
    renderedView, showConstraints, setShowConstraints, handleView, handleDataMode,
  } = useMapViewControls({ view, setView, dataMode, setDataMode, isMobile });

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

  // Keep cards separate when both maps are visible.
  const [hoveredSp, setHoveredSp] = useState<Record<PaneSide, PaneSp | null>>({
    prediction: null,
    actual: null,
  });
  const [pinnedSp, setPinnedSp] = useState<Record<PaneSide, PaneSp | null>>({
    prediction: null,
    actual: null,
  });

  // Ranked constraints for the selected delivery day.
  const [ranked, setRanked] = useState<RankedConstraints | null>(null);
  const [rankedLoading, setRankedLoading] = useState(false);
  const [constraintBasis, setConstraintBasis] =
    useState<"predicted" | "realized">(
      view === "market" ? "realized" : "predicted"
    );

  // A single-source map defaults the constraint ranking to that same source.
  // Compare and Error intentionally retain the user's last basis: both sources
  // are relevant in those views.
  useEffect(() => {
    if (view === "forecast") setConstraintBasis("predicted");
    else if (view === "market") setConstraintBasis("realized");
  }, [view]);

  // Hover temporarily overrides the selected constraint.
  const [hoveredConstraintId, setHoveredConstraintId] =
    useState<string | null>(null);
  const [lockedConstraintId, setLockedConstraintId] =
    useState<string | null>(null);
  const effectiveConstraintId = hoveredConstraintId ?? lockedConstraintId;
  // Hovering a constraint recolors its footprint without opening a card.
  const [focusReach, setFocusReach] = useState<ConstraintReach | null>(null);
  const focusReqRef = useRef(0);
  const focusReachCache = useRef<Map<string, ConstraintReach>>(new Map());
  const [hoveredMemberSp, setHoveredMemberSp] = useState<string | null>(null);
  const [exposures, setExposures] = useState<Record<PaneSide, ExposuresResponse | null>>({
    prediction: null,
    actual: null,
  });
  const [exposuresLoading, setExposuresLoading] = useState<Record<PaneSide, boolean>>({
    prediction: false,
    actual: false,
  });
  const [reach, setReach] = useState<ConstraintReach | null>(null);
  const { topology, topologyReady, overview } = useMapBootstrap(setConnState);
  const { loadRanked, loadExposures: requestExposures, loadReach } = useConstraintSelection();

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

  const {
    cursorTs, deliveryDay, isPreviewDay, spRows, forecastRows, lambdaSource,
    errorRows, conditionsStats, networkStats, spDecomp,
  } = useMapCursorData(timestamps, currentIndex, forecastRunId);
  const scorecard = useMapScorecard(deliveryDay, forecastRunId);

  const focusReachKey = useCallback(
    (id: string) => `${deliveryDay ?? "latest"}|${id}`,
    [deliveryDay]
  );

  // Cancel stale ranking requests when the day or basis changes.
  useEffect(() => {
    const controller = new AbortController();
    queueMicrotask(() => setRankedLoading(true));
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

  const exposureReqRef = useRef<Record<PaneSide, number>>({ prediction: 0, actual: 0 });
  const reachReqRef = useRef(0);
  // Preview reaches disappear when the pointer leaves.
  const previewReachRef = useRef(false);
  const setSelectionRoute = useCallback((target: MapTarget) => {
    handledTargetRef.current = `${target.kind}:${target.value}`;
    setTargetUnavailable(false);
    selectTarget(target);
  }, [selectTarget]);

  // Ignore driver responses for a node or hour that is no longer selected.
  const loadExposures = useCallback(
    (side: PaneSide, spId: string) => {
      const token = ++exposureReqRef.current[side];
      requestExposures(spId, cursorTs)
        .then((r) => {
          if (exposureReqRef.current[side] === token) {
            setExposures((current) => ({ ...current, [side]: r }));
          }
        })
        .catch(() => {
          if (exposureReqRef.current[side] === token) {
            setExposures((current) => ({ ...current, [side]: null }));
          }
        })
        .finally(() => {
          if (exposureReqRef.current[side] === token) {
            setExposuresLoading((current) => ({ ...current, [side]: false }));
          }
        });
    },
    [cursorTs, requestExposures]
  );

  const handleSpClickPrediction = useCallback(
    (spId: string, props: Record<string, unknown>, writeRoute = true) => {
      if (writeRoute) setSelectionRoute({ kind: "sp", value: spId });
      setReach(null); // a node click leaves constraint-reach mode
      reachReqRef.current++;
      previewReachRef.current = false;
      setLockedConstraintId(null);
      setHoveredConstraintId(null);
      setPinnedSp((current) => ({
        ...current,
        prediction: { spId, props, side: "prediction", spState: spDecomp(spId) },
      }));
      setExposures((current) => ({ ...current, prediction: null }));
      setExposuresLoading((current) => ({ ...current, prediction: true }));
      exposureReqRef.current.prediction++;
    },
    [spDecomp, setSelectionRoute]
  );

  const pinnedPredictionSp = pinnedSp.prediction?.spId;

  // Refresh driver values as the selected hour changes.
  useEffect(() => {
    if (!pinnedPredictionSp) return;
    loadExposures("prediction", pinnedPredictionSp);
  }, [pinnedPredictionSp, loadExposures]);

  const pinnedActualSp = pinnedSp.actual?.spId;
  useEffect(() => {
    if (!pinnedActualSp) return;
    loadExposures("actual", pinnedActualSp);
  }, [pinnedActualSp, loadExposures]);

  const handleSpClickActual = useCallback(
    (spId: string, props: Record<string, unknown>) => {
      setSelectionRoute({ kind: "sp", value: spId });
      setReach(null);
      reachReqRef.current++;
      previewReachRef.current = false;
      setLockedConstraintId(null);
      setHoveredConstraintId(null);
      setPinnedSp((current) => ({
        ...current,
        actual: { spId, props, side: "actual", spState: spDecomp(spId) },
      }));
      setExposures((current) => ({ ...current, actual: null }));
      setExposuresLoading((current) => ({ ...current, actual: true }));
      exposureReqRef.current.actual++;
    },
    [spDecomp, setSelectionRoute]
  );

  const handleClearPinnedSp = useCallback((side: "prediction" | "actual") => {
    setPinnedSp((current) => ({ ...current, [side]: null }));
    setExposures((current) => ({ ...current, [side]: null }));
    setExposuresLoading((current) => ({ ...current, [side]: false }));
    exposureReqRef.current[side]++;
  }, []);

  const handleConstraintClick = useCallback((
    constraintKey: string,
    writeRoute = true,
    side: PaneSide = "prediction",
  ) => {
    if (writeRoute) setSelectionRoute({ kind: "constraint", value: constraintKey });
    setPinnedSp((current) => ({ ...current, [side]: null }));
    setExposures((current) => ({ ...current, [side]: null }));
    exposureReqRef.current[side]++;
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

  // Apply node and constraint links once the map and cursor are ready.
  useEffect(() => {
    if (!target) {
      handledTargetRef.current = null;
      queueMicrotask(() => setTargetUnavailable(false));
      return;
    }
    const key = `${target.kind}:${target.value}`;
    if (handledTargetRef.current === key) return;

    if (!cursorTs) return;

    if (target.kind === "sp") {
      if (!topologyReady) return;
      handledTargetRef.current = key;
      const feature = spPoints?.features.find((point) =>
        (point.properties?.sp_id as string | undefined) === target.value
      );
      if (!feature) {
        queueMicrotask(() => setTargetUnavailable(true));
        return;
      }
      queueMicrotask(() => setTargetUnavailable(false));
      queueMicrotask(() =>
        handleSpClickPrediction(
          target.value,
          (feature.properties ?? { sp_id: target.value }) as Record<string, unknown>,
          false,
        )
      );
      return;
    }

    handledTargetRef.current = key;
    queueMicrotask(() => setTargetUnavailable(false));
    queueMicrotask(() => {
      setPinnedSp((current) => ({ ...current, prediction: null }));
      setExposures((current) => ({ ...current, prediction: null }));
      setHoveredConstraintId(null);
    });
    exposureReqRef.current.prediction++;
    previewReachRef.current = false;
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

  // Load the active constraint footprint for map highlighting.
  useEffect(() => {
    const id = effectiveConstraintId;
    if (!id) {
      focusReqRef.current++;
      queueMicrotask(() => setFocusReach(null));
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

  const handleConstraintHover = useCallback((id: string | null) => {
    setHoveredConstraintId(id);
  }, []);

  const handleConstraintLock = useCallback((id: string, writeRoute = true) => {
    if (writeRoute) setSelectionRoute({ kind: "constraint", value: id });
    setLockedConstraintId(id);
    setHoveredConstraintId(null);
  }, [setSelectionRoute]);

  const clearFocus = useCallback(() => {
    setLockedConstraintId(null);
    setHoveredConstraintId(null);
  }, []);

  const handleConstraintSelectFromCard = useCallback(
    (key: string) => {
      handleConstraintClick(key);
      handleConstraintLock(key, false);
    },
    [handleConstraintClick, handleConstraintLock]
  );

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

  const handleActualMemberSelect = useCallback(
    (sp: string) => {
      setHoveredMemberSp(null);
      const feat = spPoints?.features.find(
        (f) => (f.properties?.sp_id as string | undefined) === sp
      );
      handleSpClickActual(
        sp,
        (feat?.properties ?? { sp_id: sp }) as Record<string, unknown>,
      );
    },
    [spPoints, handleSpClickActual]
  );

  // Preview a reach only when no card is pinned.
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

  const handlePredictionMapBackgroundClick = useCallback(() => {
    handleClearPinnedSp("prediction");
    handleCloseReach();
    clearFocus();
  }, [handleClearPinnedSp, handleCloseReach, clearFocus]);
  const handleActualMapBackgroundClick = useCallback(() => {
    handleClearPinnedSp("actual");
    handleCloseReach();
    clearFocus();
  }, [handleClearPinnedSp, handleCloseReach, clearFocus]);

  // Keep pinned values in sync with playback.
  useEffect(() => {
    queueMicrotask(() => setPinnedSp((current) => {
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
    }));
  }, [spRows, forecastRows]); // eslint-disable-line react-hooks/exhaustive-deps

  const hasForecast = forecastRows.length > 0;
  const leftRows = forecastRows;
  // Match the realized scale when both sides are available.
  const leftMcStats = congestionStats ?? forecastCongestionStats;
  const leftLmpStats = sppStats ?? forecastLmpStats;

  const litFor = (rows: SpRow[]) =>
    rows.filter((r) => (dataMode === "lmp" ? r.spp != null : r.congestion != null))
      .length;
  const litCount = litFor(spRows);
  const cursorLabel = timestamps[currentIndex]
    ? `${formatCT(timestamps[currentIndex], "MMM d, HH:mm")} CT`
    : "—";
  const badgeProps = { cursorLabel, nodeCount: featCount, emptyTopology: spTopologyEmpty };

  const predictionLabel =
    hasForecast && forecastRunId
      ? `Prediction Model: forecast ${forecastRunId}`
      : "Prediction Model: no forecast this window";

  const constraintsToggle = overview?.constraints.length
    ? { checked: showConstraints, onChange: setShowConstraints }
    : undefined;
  const lambdaIndicative = lambdaSource === "persisted";

  const predictionInteractions: MapPaneInteractions = {
    hoveredSp: hoveredSp.prediction,
    pinnedSp: pinnedSp.prediction,
    reach,
    focusReach,
    effectiveConstraintId,
    exposures: exposures.prediction,
    exposuresLoading: exposuresLoading.prediction,
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
  const marketInteractions: MapPaneInteractions = {
    hoveredSp: hoveredSp.actual,
    pinnedSp: pinnedSp.actual,
    reach,
    focusReach,
    effectiveConstraintId,
    exposures: exposures.actual,
    exposuresLoading: exposuresLoading.actual,
    hoveredMemberSp,
    onMapBackgroundClick: handleActualMapBackgroundClick,
    onSpHover: handleSpHoverRight,
    onSpClick: handleSpClickActual,
    onMapReady: handleRightReady,
    onIsolateConstraint: handleConstraintHover,
    onConstraintPreview: handleConstraintPreview,
    onConstraintSelect: (key) => {
      handleConstraintClick(key, true, "actual");
      handleConstraintLock(key, false);
    },
    onHoverConstraint: handleConstraintHover,
    onClearPinned: () => handleClearPinnedSp("actual"),
    onCloseReach: handleCloseReach,
    onHoverMember: setHoveredMemberSp,
    onSelectMember: handleActualMemberSelect,
  };

  const forecastConfig: MapPaneConfig = {
    view: "forecast",
    side: "prediction",
    valueMode: "forecast",
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

  const errorLit = errorRows.filter((r) => r.congestion != null).length;
  const errorLabel =
    hasForecast && forecastRunId
      ? "Forecast Error: Prediction Model − ERCOT DAM"
      : "Forecast Error: no forecast this window";
  const errorConfig: MapPaneConfig = {
    view: "error",
    side: "prediction",
    valueMode: "forecast",
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
    <MapPane config={forecastConfig} interactions={predictionInteractions} {...sharedPaneProps} />
  );
  const marketConfig: MapPaneConfig = {
    view: "market",
    side: "actual",
    valueMode: "ercot",
    rows: spRows,
    lmpStats: sppStats,
    mcStats: congestionStats,
    dataMode,
    label: "ERCOT: Day Ahead Market (DAM)",
    litCount,
    litNoun: "priced",
    litHint: "Nodes with a published ERCOT DAM settlement price (SPP) at this hour (colored on the map). Resource nodes (RN / CC / PUN) carry no published price, so this is fewer than the model's forecast count.",
  };
  const marketPane = (
    <MapPane config={marketConfig} interactions={marketInteractions} {...sharedPaneProps} />
  );
  const errorPane = (
    <MapPane config={errorConfig} interactions={predictionInteractions} {...sharedPaneProps} />
  );

  const sidePanelProps = {
    network: networkStats,
    conditions: conditionsStats,
    mapView: renderedView,
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

        <SidePanel {...sidePanelProps} />
      </div>

      {isMobile && (
        <MobileDrawer
          open={mobileDrawerOpen}
          onClose={() => setMobileDrawerOpen(false)}
        >
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
