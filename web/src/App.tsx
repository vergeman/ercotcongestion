import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import type maplibregl from "maplibre-gl";
import type {
  SpRow,
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
  getAvailableTimestamps,
} from "./api/prefetch";
import {
  computeLmpStats,
  computeModeledCongestionStats,
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
  spState: {
    congestion: number | null;
    spp: number | null;
  } | null;
}

export default function App() {
  const [topology, setTopology] = useState<unknown | null>(null);
  // Prediction (left) and actual ERCOT (right) both render the quantity this
  // palette selects. Prediction is a placeholder that shows the same realized
  // values until the forecast lands (Phase 2); only the left source changes then.
  const [viewMode, setViewMode] = useState<ViewMode>("congestion");
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

  const handleLoadWindow = useCallback(
    async (start: Date, end: Date, cursorTs?: Date) => {
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
          for (const t of ts) {
            const c = getErcotCached(t);
            if (c) for (const s of c.sps) allCong.push(s.congestion);
            const s = getErcotSppCached(t);
            if (s) for (const sp of s.sps) allSpp.push(sp.spp);
          }
          setCongestionStats(
            allCong.length ? computeModeledCongestionStats(allCong) : null
          );
          setSppStats(allSpp.length ? computeLmpStats(allSpp) : null);

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
      if (event.suggested_view) setViewMode(event.suggested_view);
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

  const spStateFor = useCallback(
    (spId: string) => {
      const row = spRows.find((r) => r.sp_id === spId);
      return row ? { congestion: row.congestion, spp: row.spp } : null;
    },
    [spRows]
  );

  const handleSpHover = useCallback(
    (spId: string | null, props: Record<string, unknown> | null) => {
      if (!spId || !props) {
        setHoveredSp(null);
        return;
      }
      setHoveredSp({ spId, props, spState: spStateFor(spId) });
    },
    [spStateFor]
  );

  // Request-id guards so a slow in-flight fetch can't clobber a newer click.
  const exposureReqRef = useRef(0);
  const reachReqRef = useRef(0);

  const handleSpClick = useCallback(
    (spId: string, props: Record<string, unknown>) => {
      setReach(null); // a node click leaves constraint-reach mode
      reachReqRef.current++;
      setPinnedSp({ spId, props, spState: spStateFor(spId) });
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
    [spStateFor]
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

  // Which constraint centroids glow on the overlay: the pinned node's drivers,
  // or the single constraint being reached.
  const highlightedConstraints = useMemo(() => {
    if (reach) return new Set([reach.constraint_key]);
    if (exposures)
      return new Set(exposures.exposures.map((e) => e.constraint_key));
    return new Set<string>();
  }, [reach, exposures]);

  // Keep a pinned SP's readout fresh as playback advances.
  useEffect(() => {
    if (!pinnedSp) return;
    const fresh = spStateFor(pinnedSp.spId);
    if (
      fresh?.congestion !== pinnedSp.spState?.congestion ||
      fresh?.spp !== pinnedSp.spState?.spp
    ) {
      setPinnedSp({ ...pinnedSp, spState: fresh });
    }
  }, [spRows]); // eslint-disable-line react-hooks/exhaustive-deps

  const litCount = spRows.filter((r) =>
    viewMode === "lmp" ? r.spp != null : r.congestion != null
  ).length;
  const badgeFor = (label: string) =>
    spTopologyEmpty
      ? `${label} · no SPs (rebuild topology cache)`
      : `${label} · ${featCount} SPs · ${litCount} lit`;

  const paneProps = {
    points: spPoints,
    rows: spRows,
    viewMode,
    lmpStats: sppStats,
    mcStats: congestionStats,
    onSpHover: handleSpHover,
    onSpClick: handleSpClick,
    onMapClick: handleMapBackgroundClick,
    selectedSpId: pinnedSp?.spId ?? null,
  };

  const leftPane = (
    <>
      <GridMap
        {...paneProps}
        side="prediction"
        onMapReady={handleMainReady}
        constraints={constraints}
        showConstraints={showConstraints}
        highlightedConstraints={highlightedConstraints}
        onConstraintClick={handleConstraintClick}
        reach={reach}
        overview={overview}
      />
      <div className="pane-badge">{badgeFor("PREDICTION · placeholder")}</div>
      <Legend
        viewMode={viewMode}
        rows={spRows}
        lmpStats={sppStats}
        mcStats={congestionStats}
        variant="palette-only"
        paneLabel="PREDICTION · placeholder (= actual)"
        constraintOverlay={showConstraints && !!constraints?.length}
      />
    </>
  );

  const rightPane = (
    <>
      <GridMap {...paneProps} side="actual" onMapReady={handleRightReady} />
      <div className="pane-badge">{badgeFor("ERCOT · actual")}</div>
      <Legend
        viewMode={viewMode}
        rows={spRows}
        lmpStats={sppStats}
        mcStats={congestionStats}
        variant="full"
        paneLabel="ERCOT · actual"
      />
    </>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <Header
        viewMode={viewMode}
        onViewMode={setViewMode}
        lastUpdated={lastUpdated}
        connectionState={connState}
        showConstraints={showConstraints}
        onToggleConstraints={
          constraints?.length ? setShowConstraints : undefined
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
        {/* Paired split: left = prediction placeholder, right = actual ERCOT.
            Both render the same quantity under the active palette. */}
        <div style={{ flex: 1, position: "relative" }}>
          <CompareMap main={leftPane} right={rightPane} />
          <DetailCard
            hoveredSp={hoveredSp}
            pinnedSp={pinnedSp}
            exposures={exposures}
            exposuresLoading={exposuresLoading}
            reach={reach}
            onClose={handleClearPinnedSp}
            onCloseReach={handleCloseReach}
            onSelectConstraint={handleConstraintClick}
          />
          <style>{`
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
