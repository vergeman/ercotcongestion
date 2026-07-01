import { useState, useEffect, useCallback } from "react";
import type { BusState, SnapshotMeta, ViewMode } from "./api/types";
import { fetchTopology } from "./api/client";
import {
  prefetchWindow,
  getCached,
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
import ValidationPanel from "./components/panels/ValidationPanel";
import Legend from "./components/map/Legend";
import DateRangePicker from "./components/playback/DateRangePicker";
import DetailCard from "./components/map/DetailCard";
import { CURATED_EVENTS, type CuratedEvent } from "./lib/events";

type ConnectionState = "ok" | "error" | "loading";
type PanelTab = "stats" | "validation";

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

  const [panelTab, setPanelTab] = useState<PanelTab>("stats");
  // The validation panel needs the loaded window — keep it lifted in App
  // so it persists across tab switches and updates with new range loads.
  const [loadedWindow, setLoadedWindow] = useState<{
    start: Date;
    end: Date;
  } | null>(null);
  // Window-wide LMP stats (median + MAD). Computed once on window load and
  // reused for every frame so coloring is stable across playback.
  const [lmpStats, setLmpStats] = useState<LmpStats | null>(null);
  // Window-wide modeled-congestion stats (|mc| P99 anchor, symmetric around 0).
  // Same shape as lmpStats — stable palette across playback.
  const [mcStats, setMcStats] = useState<ModeledCongestionStats | null>(null);
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

  // Snapshot data on scrub
  useEffect(() => {
    if (!timestamps.length) return;
    const ts = timestamps[currentIndex];
    const entry = getCached(ts);
    if (entry) {
      setBuses(entry.buses);
      setMeta(entry.meta as SnapshotMeta);
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
          setLoadedWindow({ start, end });
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
        {/* Map */}
        <div style={{ flex: 1, position: "relative" }}>
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
          />
        </div>

        {/* Right panel — tabbed: stats or validation */}
        <div className="right-panel-wrap">
          <div className="panel-tabs">
            <button
              className={panelTab === "stats" ? "active" : ""}
              onClick={() => setPanelTab("stats")}
            >
              Stats
            </button>
            <button
              className={panelTab === "validation" ? "active" : ""}
              onClick={() => setPanelTab("validation")}
            >
              Validation
            </button>
          </div>
          {panelTab === "stats" ? (
            <StatsPanel meta={meta} />
          ) : (
            <ValidationPanel
              start={loadedWindow?.start ?? null}
              end={loadedWindow?.end ?? null}
            />
          )}
        </div>
      </div>

      <style>{`
                .right-panel-wrap {
                    display: flex;
                    flex-direction: column;
                    width: var(--panel-w);
                    border-left: 1px solid var(--border);
                    background: var(--bg-panel);
                }
                .panel-tabs {
                    display: flex;
                    border-bottom: 1px solid var(--border);
                    flex-shrink: 0;
                }
                .panel-tabs button {
                    flex: 1;
                    border: none;
                    border-radius: 0;
                    border-right: 1px solid var(--border);
                    padding: 8px 0;
                    background: var(--bg-panel);
                    color: var(--text-secondary);
                    font-family: 'Barlow Condensed', sans-serif;
                    font-weight: 600;
                    font-size: 11px;
                    letter-spacing: 0.1em;
                    text-transform: uppercase;
                }
                .panel-tabs button:last-child { border-right: none; }
                .panel-tabs button.active {
                    background: var(--bg-base);
                    color: var(--accent);
                    box-shadow: inset 0 -2px 0 var(--accent);
                }
                /* When wrapped, the inner panels shouldn't double the border. */
                .right-panel-wrap .stats-panel,
                .right-panel-wrap .validation-panel {
                    border-left: none;
                    width: 100%;
                    flex: 1;
                }
            `}</style>

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
