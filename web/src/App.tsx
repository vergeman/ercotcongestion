import { useState, useEffect, useCallback } from 'react';
import type { BusState, SnapshotMeta, ViewMode } from './api/types';
import { fetchTopology } from './api/client';
import { prefetchWindow, getCached, getAvailableTimestamps } from './api/prefetch';
import Header from './components/layout/Header';
import GridMap from './components/map/GridMap';
import PlaybackScrubber from './components/playback/PlaybackScrubber';
import StatsPanel from './components/panels/StatsPanel';
import Legend from './components/map/Legend';
import DateRangePicker from './components/playback/DateRangePicker';

type ConnectionState = 'ok' | 'error' | 'loading';

export default function App() {
  const [topology, setTopology] = useState<unknown | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('fragility');
  const [timestamps, setTimestamps] = useState<Date[]>([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [buses, setBuses] = useState<BusState[]>([]);
  const [meta, setMeta] = useState<SnapshotMeta | null>(null);
  const [loading, setLoading] = useState(false);
  const [connState, setConnState] = useState<ConnectionState>('loading');
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [hoveredBus, setHoveredBus] = useState<{
    busId: string;
    props: Record<string, unknown>;
    busState: BusState | null;
  } | null>(null);

  // Load topology on mount
  useEffect(() => {
    fetchTopology()
      .then((t) => {
        setTopology(t);
        setConnState('ok');
      })
      .catch(() => setConnState('error'));
  }, []);

  // When current index changes, pull from cache
  useEffect(() => {
    if (!timestamps.length) return;
    const ts = timestamps[currentIndex];
    const entry = getCached(ts);
    if (entry) {
      setBuses(entry.buses);
      setMeta(entry.meta as SnapshotMeta);
    }
  }, [currentIndex, timestamps]);

  const handleLoadWindow = useCallback(async (start: Date, end: Date) => {
    setLoading(true);
    setConnState('loading');
    try {
      await prefetchWindow(start, end);
      const ts = getAvailableTimestamps();
      setTimestamps(ts);
      if (ts.length > 0) {
        setCurrentIndex(ts.length - 1);
        setLastUpdated(new Date());
        setConnState('ok');
      } else {
        setConnState('error');
      }
    } catch {
      setConnState('error');
    } finally {
      setLoading(false);
    }
  }, []);

  // Load most recent 6h on topology load
  useEffect(() => {
    if (!topology) return;
    const now = new Date();
    const sixHAgo = new Date(now.getTime() - 6 * 3600 * 1000);
    handleLoadWindow(sixHAgo, now);
  }, [topology]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleBusHover = useCallback(
    (busId: string | null, props: Record<string, unknown> | null) => {
      if (!busId || !props) {
        setHoveredBus(null);
        return;
      }
      const busState = buses.find((b) => b.bus_id === busId) ?? null;
      setHoveredBus({ busId, props, busState });
    },
    [buses]
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Header
        viewMode={viewMode}
        onViewMode={setViewMode}
        lastUpdated={lastUpdated}
        connectionState={connState}
      />

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>
        {/* Map */}
        <div style={{ flex: 1, position: 'relative' }}>
          <GridMap
            topology={topology}
            buses={buses}
            meta={meta}
            viewMode={viewMode}
            onBusHover={handleBusHover}
          />
          <Legend viewMode={viewMode} />
        </div>

        {/* Right panel */}
        <StatsPanel meta={meta} hoveredBus={hoveredBus} />
      </div>

      {/* Bottom scrubber */}
      <div style={{ display: 'flex', alignItems: 'stretch', background: 'var(--bg-panel)', borderTop: '1px solid var(--border)' }}>
        <div style={{ padding: '0 12px', display: 'flex', alignItems: 'center', borderRight: '1px solid var(--border)' }}>
          <DateRangePicker onLoad={handleLoadWindow} loading={loading} />
        </div>
        <div style={{ flex: 1 }}>
          <PlaybackScrubber
            timestamps={timestamps}
            currentIndex={currentIndex}
            onIndexChange={setCurrentIndex}
            loading={loading}
          />
        </div>
      </div>
    </div>
  );
}
