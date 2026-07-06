import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import type maplibregl from "maplibre-gl";
import type {
  BusState,
  ScorecardResponse,
  SnapshotMeta,
  SPFeatureProperties,
  ViewMode,
} from "./api/types";
import { fetchScorecard, fetchTopology } from "./api/client";
import {
  prefetchWindow,
  getCached,
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
interface HoveredSp {
  spId: string;
  props: Record<string, unknown>;
  spState: { congestion: number | null; spp: number | null } | null;
}

// The right pane's ERCOT counterpart depends on the active palette.
// Kept as a helper so the render tree below stays declarative.
type RightPaneKind = "ercot_congestion" | "ercot_spp" | "empty";
function rightPaneFor(vm: ViewMode): RightPaneKind {
  if (vm === "modeled_congestion") return "ercot_congestion";
  if (vm === "lmp") return "ercot_spp";
  return "empty";
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
  const [hoveredSp, setHoveredSp] = useState<HoveredSp | null>(null);
  const [pinnedSp, setPinnedSp] = useState<HoveredSp | null>(null);

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

  // Selecting a scorecard row auto-enables the Zones layer so the highlight
  // is visible against the palette-colored buses.
  const handleSelectCluster = useCallback((id: number | null) => {
    setSelectedClusterId(id);
    if (id != null) setShowZones(true);
  }, []);

  // Right pane consumes a bus-shaped topology so it can share GridMap
  // wholesale. SP features get their `sp_id` promoted to `bus_id` to
  // satisfy the source's `promoteId: "bus_id"`, and lines collapse to
  // empty since SPs have no wired network.
  const spTopology = useMemo(() => {
    if (!topology) return null;
    const t = topology as {
      settlement_points?: {
        type: "FeatureCollection";
        features: Array<{
          type: "Feature";
          geometry: unknown;
          properties: SPFeatureProperties;
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
  const spTopologyEmpty =
    !!topology &&
    (spTopology?.buses.features.length ?? 0) === 0;

  // Camera sync between the two panes. Refs collected via each GridMap's
  // `onMapReady`; `handleMainReady` and `handleRightReady` write in and
  // re-arm the mirror when both are present.
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
  // Right pane can unmount (binding_proximity has no counterpart). Drop the
  // stale ref so a later remount rewires the sync from scratch. Also kicks
  // MapLibre to resize since the container might have changed dimensions.
  const rightKind = rightPaneFor(viewMode);
  useEffect(() => {
    if (rightKind === "empty") {
      teardownSyncRef.current?.();
      teardownSyncRef.current = null;
      rightMapRef.current = null;
    }
    const r = requestAnimationFrame(() => {
      mainMapRef.current?.resize();
      rightMapRef.current?.resize();
    });
    return () => cancelAnimationFrame(r);
  }, [rightKind]);

  // Window-wide LMP stats. Computed once on window load and reused for
  // every frame so coloring is stable across playback.
  const [lmpStats, setLmpStats] = useState<LmpStats | null>(null);
  // Window-wide modeled-congestion stats (|mc| P90 anchor, symmetric around 0).
  const [mcStats, setMcStats] = useState<ModeledCongestionStats | null>(null);
  // Same-shape stats for the ERCOT congestion side (SPP − system_λ per SP).
  // Separate anchor so the two panes' fills stay comparable in sign but
  // not artificially matched in magnitude.
  const [ercotMcStats, setErcotMcStats] =
    useState<ModeledCongestionStats | null>(null);
  // Window-wide stats for the raw ERCOT SPP side (LMP palette family).
  const [ercotSppStats, setErcotSppStats] = useState<LmpStats | null>(null);
  // Per-current-snapshot ERCOT rows in BusState shape (bus_id = sp_id).
  // MC branch reads `modeled_congestion`; LMP branch reads `lmp`. Both are
  // populated when the corresponding cache has data for the current hour.
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

  // Snapshot data on scrub. Model buses are always populated when cached;
  // ERCOT rows carry both the congestion component (in `modeled_congestion`)
  // and the raw SPP (in `lmp`) so the right pane can share the GridMap
  // coloring path with the model side.
  useEffect(() => {
    if (!timestamps.length) return;
    const ts = timestamps[currentIndex];
    const entry = getCached(ts);
    if (entry) {
      setBuses(entry.buses);
      setMeta(entry.meta as SnapshotMeta);
    }
    const ercotEntry = getErcotCached(ts);
    const sppEntry = getErcotSppCached(ts);
    if (ercotEntry || sppEntry) {
      // Union of SP ids across both caches, so an SP that appears in only
      // one still shows up on the map (colored per whichever field is set).
      const byId = new Map<string, BusState>();
      for (const s of ercotEntry?.sps ?? []) {
        byId.set(s.sp_id, {
          bus_id: s.sp_id,
          modeled_congestion: s.congestion,
          binding_proximity: null,
          lmp: null,
          basis: null,
        });
      }
      for (const s of sppEntry?.sps ?? []) {
        const cur = byId.get(s.sp_id);
        if (cur) {
          cur.lmp = s.spp;
        } else {
          byId.set(s.sp_id, {
            bus_id: s.sp_id,
            modeled_congestion: null,
            binding_proximity: null,
            lmp: s.spp,
            basis: null,
          });
        }
      }
      setErcotBuses(Array.from(byId.values()));
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

          // Same window pass for the ERCOT side. Walk the caches rather
          // than the responses so we get the deduped, label-stripped
          // entries `prefetchWindow` already stored.
          const allErcot: Array<number | null> = [];
          const allSpp: Array<number | null> = [];
          for (const t of ts) {
            const e = getErcotCached(t);
            if (e) for (const sp of e.sps) allErcot.push(sp.congestion);
            const s = getErcotSppCached(t);
            if (s) for (const sp of s.sps) allSpp.push(sp.spp);
          }
          setErcotMcStats(
            allErcot.length ? computeModeledCongestionStats(allErcot) : null
          );
          setErcotSppStats(allSpp.length ? computeLmpStats(allSpp) : null);

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

  useEffect(() => {
    if (!pinnedBus) return;
    const fresh = buses.find((b) => b.bus_id === pinnedBus.busId) ?? null;
    if (fresh !== pinnedBus.busState) {
      setPinnedBus({ ...pinnedBus, busState: fresh });
    }
  }, [buses]); // eslint-disable-line react-hooks/exhaustive-deps

  // ERCOT pane SP interactions. GridMap fires `onBusHover(sp_id, props)` on
  // the right pane because SP features are aliased with `bus_id = sp_id`.
  const spStateFor = useCallback(
    (spId: string): { congestion: number | null; spp: number | null } | null => {
      const row = ercotBuses.find((b) => b.bus_id === spId);
      return row ? { congestion: row.modeled_congestion, spp: row.lmp } : null;
    },
    [ercotBuses]
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

  const handleSpClick = useCallback(
    (spId: string, props: Record<string, unknown>) => {
      setPinnedSp({ spId, props, spState: spStateFor(spId) });
    },
    [spStateFor]
  );

  const handleClearPinnedSp = useCallback(() => {
    setPinnedSp(null);
  }, []);

  useEffect(() => {
    if (!pinnedSp) return;
    const fresh = spStateFor(pinnedSp.spId);
    if (
      fresh?.congestion !== pinnedSp.spState?.congestion ||
      fresh?.spp !== pinnedSp.spState?.spp
    ) {
      setPinnedSp({ ...pinnedSp, spState: fresh });
    }
  }, [ercotBuses]); // eslint-disable-line react-hooks/exhaustive-deps

  // Right pane content per active palette:
  //   MC   → SP topology colored by SPP − system_λ
  //   LMP  → SP topology colored by raw SPP
  //   BP   → empty placeholder (ERCOT has no comparable signal)
  const rightPane = (() => {
    if (rightKind === "empty") {
      return (
        <div className="pane-empty">
          <div className="pane-empty__msg">
            ERCOT · no comparable signal for binding proximity
          </div>
        </div>
      );
    }
    const badge = spTopologyEmpty
      ? "ERCOT · no SPs (rebuild topology cache)"
      : `ERCOT · ${spTopology?.buses.features.length ?? 0} SPs · ${ercotBuses.length} lit`;
    return (
      <>
        <GridMap
          topology={spTopology}
          buses={ercotBuses}
          meta={null}
          viewMode={rightKind === "ercot_spp" ? "lmp" : "modeled_congestion"}
          lmpStats={rightKind === "ercot_spp" ? ercotSppStats : null}
          mcStats={rightKind === "ercot_congestion" ? ercotMcStats : null}
          onBusHover={handleSpHover}
          onLineHover={() => {}}
          onBusClick={handleSpClick}
          onLineClick={() => {}}
          onMapClick={handleClearPinnedSp}
          selectedBusId={pinnedSp?.spId ?? null}
          selectedLineId={null}
          showZones={showZones}
          tightClusterIds={tightClusterIds}
          selectedClusterId={selectedClusterId}
          side="ercot"
          onMapReady={handleRightReady}
        />
        <div className="pane-badge">{badge}</div>
        <DetailCard
          meta={null}
          hoveredBus={null}
          hoveredLine={null}
          hoveredSp={hoveredSp}
          pinnedSp={pinnedSp}
          onClose={handleClearPinnedSp}
        />
      </>
    );
  })();

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <Header
        viewMode={viewMode}
        onViewMode={setViewMode}
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
        {/* Every palette is a paired split: left = model bus grid,
            right = ERCOT counterpart appropriate to the palette. */}
        <div style={{ flex: 1, position: "relative" }}>
          <CompareMap
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
                showZones={showZones}
                tightClusterIds={tightClusterIds}
                selectedClusterId={selectedClusterId}
                side="model"
                onMapReady={handleMainReady}
              />
            }
            right={rightPane}
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
            .pane-empty {
              width: 100%;
              height: 100%;
              display: flex;
              align-items: center;
              justify-content: center;
              background: rgba(15, 18, 23, 0.4);
            }
            .pane-empty__msg {
              padding: 6px 10px;
              background: rgba(15, 18, 23, 0.85);
              border: 1px solid var(--border);
              border-radius: 3px;
              color: var(--text-muted);
              font-family: 'Barlow Condensed', sans-serif;
              font-size: 11px;
              letter-spacing: 0.06em;
              text-transform: uppercase;
            }
          `}</style>
        </div>

        <StatsPanel
          meta={meta}
          scorecard={scorecard}
          selectedClusterId={selectedClusterId}
          onSelectCluster={handleSelectCluster}
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
