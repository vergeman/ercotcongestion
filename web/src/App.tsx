import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import type maplibregl from "maplibre-gl";
import type {
  BusState,
  ComparisonMode,
  ScorecardResponse,
  SnapshotMeta,
  ViewMode,
} from "./api/types";
import { fetchScorecard, fetchTopology } from "./api/client";
import {
  prefetchWindow,
  getCached,
  getErcotCached,
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
import StatsPanel from "./components/panels/StatsPanel";
import Legend from "./components/map/Legend";
import CompareMap from "./components/map/CompareMap";
import DateRangePicker from "./components/playback/DateRangePicker";
import DetailCard from "./components/map/DetailCard";
import { CURATED_EVENTS, type CuratedEvent } from "./lib/events";

type ConnectionState = "ok" | "error" | "loading";

const RUN_ID = import.meta.env.VITE_RUN_ID ?? "v1-120";

interface HoveredBus {
  busId: string;
  props: Record<string, unknown>;
  busState: BusState | null;
}
interface HoveredLine {
  lineId: string;
  props: Record<string, unknown>;
}

export default function App() {
  const [topology, setTopology] = useState<unknown | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("modeled_congestion");
  const [timestamps, setTimestamps] = useState<Date[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [buses, setBuses] = useState<BusState[]>([]);
  const [meta, setMeta] = useState<SnapshotMeta | null>(null);
  const [loading, setLoading] = useState(false);
  const [connState, setConnState] = useState<ConnectionState>("loading");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const [hoveredBus, setHoveredBus] = useState<HoveredBus | null>(null);
  const [hoveredLine, setHoveredLine] = useState<HoveredLine | null>(null);
  const [pinnedBus, setPinnedBus] = useState<HoveredBus | null>(null);
  const [pinnedLine, setPinnedLine] = useState<HoveredLine | null>(null);

  // Zone scorecard — loaded once per run. Selection is lifted here so the
  // GridMap can highlight members and the StatsPanel row can show selected.
  const [scorecard, setScorecard] = useState<ScorecardResponse | null>(null);
  const [selectedClusterId, setSelectedClusterId] = useState<number | null>(
    null
  );
  // Zones layer toggle (S3.2). When on, buses are colored by cluster tag
  // instead of the congestion palette; selection dims non-members.
  const [showZones, setShowZones] = useState(false);
  const tightClusterIds = useMemo(
    () => new Set((scorecard?.zones ?? []).map((z) => z.cluster_id)),
    [scorecard]
  );
  // S3.3 — comparison mode. Default `split`. `single` restores the
  // ViewMode palette pills.
  const [comparisonMode, setComparisonMode] = useState<ComparisonMode>("split");

  // S3.4 — the right pane consumes a bus-shaped topology so it can share
  // GridMap wholesale. SP features get their `sp_id` promoted to `bus_id`
  // to satisfy the source's `promoteId: "bus_id"`, and lines collapse to
  // empty since SPs have no wired network.
  const spTopology = useMemo(() => {
    if (!topology) return null;
    const t = topology as {
      settlement_points?: {
        type: "FeatureCollection";
        features: Array<{
          type: "Feature";
          geometry: unknown;
          properties: { sp_id: string; [k: string]: unknown };
        }>;
      };
    };
    const sps = t.settlement_points?.features ?? [];
    return {
      buses: {
        type: "FeatureCollection",
        features: sps.map((f) => ({
          ...f,
          properties: { ...f.properties, bus_id: f.properties.sp_id },
        })),
      },
      lines: { type: "FeatureCollection", features: [] },
    };
  }, [topology]);

  // Camera sync between the two split panes. Refs collected via each
  // GridMap's `onMapReady`; `handleMainReady` and `handleRightReady` write
  // in and re-arm the mirror when both are present.
  const mainMapRef = useRef<maplibregl.Map | null>(null);
  const rightMapRef = useRef<maplibregl.Map | null>(null);
  const syncingSide = useRef<"main" | "right" | null>(null);
  const wireSync = useCallback(() => {
    const a = mainMapRef.current;
    const b = rightMapRef.current;
    if (!a || !b) return () => {};
    const drive = (from: maplibregl.Map, to: maplibregl.Map, tag: "main" | "right") => () => {
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
  useEffect(() => {
    // When the right pane unmounts (mode leaves split), drop its ref so a
    // fresh mount reattaches cleanly.
    if (comparisonMode !== "split") {
      teardownSyncRef.current?.();
      teardownSyncRef.current = null;
      rightMapRef.current = null;
    }
    // The main pane's flex-basis changes on split ↔ single/diff. Kick
    // MapLibre so it re-reads container dims.
    const r = requestAnimationFrame(() => {
      mainMapRef.current?.resize();
      rightMapRef.current?.resize();
    });
    return () => cancelAnimationFrame(r);
  }, [comparisonMode]);
  // Window-wide LMP stats (median + MAD). Computed once on window load and
  // reused for every frame so coloring is stable across playback.
  const [lmpStats, setLmpStats] = useState<LmpStats | null>(null);
  // Window-wide modeled-congestion stats (|mc| P99 anchor, symmetric around 0).
  // Same shape as lmpStats — stable palette across playback.
  const [mcStats, setMcStats] = useState<ModeledCongestionStats | null>(null);
  // S3.4 — same-shape stats for the ERCOT side, computed from the ERCOT
  // congestion values in the loaded window. Separate anchor so the two
  // panes' fills stay comparable in sign but not artificially matched in
  // magnitude.
  const [ercotMcStats, setErcotMcStats] =
    useState<ModeledCongestionStats | null>(null);
  const [ercotBuses, setErcotBuses] = useState<BusState[]>([]);
  // Per-timestamp series for the timeline sparkline
  // (modeled_congestion_abs_total + n_binding_lines). Aligned 1:1 with
  // `timestamps`.
  const [sparkSeries, setSparkSeries] = useState<SparkPoint[]>([]);
  // Currently-selected curated event, if any. Cleared whenever the user
  // loads a custom window via DateRangePicker.
  const [activeEventId, setActiveEventId] = useState<string | null>(null);

  // Topology load
  useEffect(() => {
    fetchTopology()
      .then((t) => {
        setTopology(t);
        setConnState("ok");
      })
      .catch(() => setConnState("error"));
  }, []);

  // Scorecard load — soft-fail. If the run doesn't have a scorecard yet the
  // panel section just doesn't render; nothing else depends on it.
  useEffect(() => {
    fetchScorecard(RUN_ID)
      .then(setScorecard)
      .catch(() => setScorecard(null));
  }, []);

  // Snapshot data on scrub
  useEffect(() => {
    if (!timestamps.length) return;
    const ts = timestamps[currentIndex];
    const entry = getCached(ts);
    if (entry) {
      setBuses(entry.buses);
      setMeta(entry.meta as SnapshotMeta);
    }
    // ERCOT side (S3.4). Reshape SP congestion into BusState-shaped rows so
    // the right pane can share the existing GridMap coloring path; the
    // point source treats `bus_id` as a promoteId regardless of whether
    // the id is a model bus or a settlement point.
    const ercotEntry = getErcotCached(ts);
    if (ercotEntry) {
      setErcotBuses(
        ercotEntry.sps.map((s) => ({
          bus_id: s.sp_id,
          modeled_congestion: s.congestion,
          binding_proximity: null,
          lmp: null,
          basis: null,
        }))
      );
    } else {
      setErcotBuses([]);
    }
  }, [currentIndex, timestamps]);

  const handleLoadWindow = useCallback(
    async (start: Date, end: Date, cursorTs?: Date) => {
      setLoading(true);
      setConnState("loading");
      try {
        const data = await prefetchWindow(start, end);
        const ts = getAvailableTimestamps();
        setTimestamps(ts);
        if (ts.length > 0) {
          // Build window-wide LMP + modeled-congestion stats from every
          // (bus, snapshot) pair in one pass.
          const allLmp: Array<number | null> = [];
          const allMc: Array<number | null> = [];
          for (const entry of data.entries) {
            for (const b of entry.buses) {
              allLmp.push(b.lmp);
              allMc.push(b.modeled_congestion);
            }
          }
          setLmpStats(computeLmpStats(allLmp));
          setMcStats(computeModeledCongestionStats(allMc));

          // Same window pass for the ERCOT side (S3.4). Walk the cache
          // rather than the response so we get the deduped, label-stripped
          // entries `prefetchWindow` already stored.
          const allErcot: Array<number | null> = [];
          for (const t of ts) {
            const e = getErcotCached(t);
            if (!e) continue;
            for (const sp of e.sps) allErcot.push(sp.congestion);
          }
          setErcotMcStats(
            allErcot.length ? computeModeledCongestionStats(allErcot) : null
          );

          // Build sparkline series — one point per timestamp, in the same order.
          // We walk `ts` and pull from the cached entries via interval_ts to
          // guarantee alignment with the slider index.
          const byTs = new Map<string, SparkPoint>();
          for (const entry of data.entries) {
            byTs.set(new Date(entry.interval_ts).toISOString(), {
              modeled_congestion_abs_total:
                entry.meta.modeled_congestion_abs_total,
              n_binding_lines: entry.meta.n_binding_lines,
            });
          }
          setSparkSeries(
            ts.map(
              (t) =>
                byTs.get(t.toISOString()) ?? {
                  modeled_congestion_abs_total: null,
                  n_binding_lines: null,
                }
            )
          );

          // If a cursor target was given (curated event), snap to the closest
          // available frame. Otherwise start at the beginning.
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

  // Handler for curated events: load window, snap cursor, optionally switch view.
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

  // Wrapper for the date picker — clears event selection on custom load.
  const handleCustomLoadWindow = useCallback(
    (start: Date, end: Date) => {
      setActiveEventId(null);
      handleLoadWindow(start, end);
    },
    [handleLoadWindow]
  );

  const handleBusHover = useCallback(
    (busId: string | null, props: Record<string, unknown> | null) => {
      if (!busId || !props) {
        setHoveredBus(null);
        return;
      }
      const busState = buses.find((b) => b.bus_id === busId) ?? null;
      setHoveredBus({ busId, props, busState });
      setHoveredLine(null);
    },
    [buses]
  );

  const handleLineHover = useCallback(
    (lineId: string | null, props: Record<string, unknown> | null) => {
      if (!lineId || !props) {
        setHoveredLine(null);
        return;
      }
      setHoveredLine({ lineId, props });
      setHoveredBus(null);
    },
    []
  );

  const handleBusClick = useCallback(
    (busId: string, props: Record<string, unknown>) => {
      const busState = buses.find((b) => b.bus_id === busId) ?? null;
      setPinnedBus({ busId, props, busState });
      setPinnedLine(null);
    },
    [buses]
  );

  const handleLineClick = useCallback(
    (lineId: string, props: Record<string, unknown>) => {
      setPinnedLine({ lineId, props });
      setPinnedBus(null);
    },
    []
  );

  const handleClearPinned = useCallback(() => {
    setPinnedBus(null);
    setPinnedLine(null);
  }, []);

  // Diff-mode per-cluster delta at the current scrubber hour.
  // Snaps the timestamp to the closest hour in `scorecard.series.hours`
  // (within a 90-minute tolerance); returns null when the scorecard is
  // absent, empty, or the cursor lands outside the covered window.
  const busClusterDelta = useMemo(() => {
    if (comparisonMode !== "diff") return null;
    if (!scorecard || !timestamps.length) return null;
    const s = scorecard.series;
    if (!s.hours.length || !s.cluster_ids.length) return null;
    const targetMs = timestamps[currentIndex].getTime();
    let bestIdx = -1;
    let bestDelta = Infinity;
    for (let i = 0; i < s.hours.length; i++) {
      // Scorecard hours ship as ``<scenario_label>|<iso>``; drop the label
      // before parsing.
      const iso = s.hours[i].split("|", 2)[1] ?? s.hours[i];
      const t = new Date(iso).getTime();
      if (!isFinite(t)) continue;
      const d = Math.abs(t - targetMs);
      if (d < bestDelta) {
        bestDelta = d;
        bestIdx = i;
      }
    }
    if (bestIdx < 0 || bestDelta > 90 * 60 * 1000) return null;
    const modelRow = s.model_Z[bestIdx] ?? [];
    const ercotRow = s.ercot_Z[bestIdx] ?? [];
    const out = new Map<number, number>();
    for (let j = 0; j < s.cluster_ids.length; j++) {
      const m = modelRow[j];
      const e = ercotRow[j];
      if (m == null || e == null || !isFinite(m) || !isFinite(e)) continue;
      out.set(s.cluster_ids[j], m - e);
    }
    return out;
  }, [comparisonMode, scorecard, timestamps, currentIndex]);

  useEffect(() => {
    if (!pinnedBus) return;
    const fresh = buses.find((b) => b.bus_id === pinnedBus.busId) ?? null;
    if (fresh !== pinnedBus.busState) {
      setPinnedBus({ ...pinnedBus, busState: fresh });
    }
  }, [buses]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <Header
        viewMode={viewMode}
        onViewMode={setViewMode}
        comparisonMode={comparisonMode}
        onComparisonMode={setComparisonMode}
        lastUpdated={lastUpdated}
        connectionState={connState}
      />

      <div
        style={{
          flex: 1,
          display: "flex",
          overflow: "hidden",
          position: "relative",
        }}
      >
        {/* Map — layout branches on comparisonMode. Main GridMap stays
            mounted across all modes so camera + pinned state survive
            mode switches. Diff mode swaps coloring via `busClusterDelta`;
            split adds a synced ERCOT pane on the right. */}
        <div style={{ flex: 1, position: "relative" }}>
          <CompareMap
            mode={comparisonMode}
            main={
              <GridMap
                topology={topology}
                buses={buses}
                meta={meta}
                viewMode={viewMode}
                lmpStats={lmpStats}
                mcStats={mcStats}
                onBusHover={handleBusHover}
                onLineHover={handleLineHover}
                onBusClick={handleBusClick}
                onLineClick={handleLineClick}
                onMapClick={handleClearPinned}
                selectedBusId={pinnedBus?.busId ?? null}
                selectedLineId={pinnedLine?.lineId ?? null}
                showZones={comparisonMode === "diff" ? false : showZones}
                tightClusterIds={tightClusterIds}
                selectedClusterId={selectedClusterId}
                side="model"
                onMapReady={handleMainReady}
                busClusterDelta={
                  comparisonMode === "diff" ? busClusterDelta : null
                }
              />
            }
            right={
              <>
                <GridMap
                  topology={spTopology}
                  buses={ercotBuses}
                  meta={null}
                  viewMode="modeled_congestion"
                  lmpStats={null}
                  mcStats={ercotMcStats}
                  onBusHover={() => {}}
                  onLineHover={() => {}}
                  onBusClick={() => {}}
                  onLineClick={() => {}}
                  onMapClick={() => {}}
                  selectedBusId={null}
                  selectedLineId={null}
                  showZones={false}
                  tightClusterIds={tightClusterIds}
                  selectedClusterId={null}
                  side="ercot"
                  onMapReady={handleRightReady}
                />
                <div className="pane-badge">
                  ERCOT · {ercotBuses.length} SPs
                </div>
              </>
            }
          />
          <DetailCard
            meta={meta}
            hoveredBus={hoveredBus}
            hoveredLine={hoveredLine}
            pinnedBus={pinnedBus}
            pinnedLine={pinnedLine}
            onClose={handleClearPinned}
          />
          <Legend
            viewMode={viewMode}
            buses={buses}
            lmpStats={lmpStats}
            mcStats={mcStats}
            showZones={showZones}
            onToggleZones={() => setShowZones((s) => !s)}
            tightClusterIds={tightClusterIds}
            comparisonMode={comparisonMode}
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

        <StatsPanel
          meta={meta}
          scorecard={scorecard}
          selectedClusterId={selectedClusterId}
          onSelectCluster={setSelectedClusterId}
        />
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
