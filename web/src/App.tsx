import Header from "./components/layout/Header";
import DateRangePicker from "./components/playback/DateRangePicker";
import PlaybackScrubber from "./components/playback/PlaybackScrubber";
import { useExplorerSession } from "./hooks/useExplorerSession";
import { CURATED_EVENTS } from "./lib/events";
import { useExplorerRoute } from "./lib/explorerRoute";
import MapWorkspace from "./workspaces/MapWorkspace";
import MatrixWorkspace from "./workspaces/MatrixWorkspace";

/** Persistent live-data shell shared by the Map and Matrix workspaces. */
export default function App() {
  const { workspace, search, navigate } = useExplorerRoute();
  const session = useExplorerSession();
  const {
    timestamps,
    currentIndex,
    setCurrentIndex,
    loading,
    connectionState,
    lastUpdated,
    sparkSeries,
    activeEventId,
    selectEvent,
    loadCustomWindow,
  } = session;

  return (
    <div className="app-shell">
      {/* Keep MapWorkspace alive across route changes: its map-only state and
          one-time map requests survive a visit to Matrix. */}
      <div style={{ display: workspace === "map" ? "contents" : "none" }}>
        <MapWorkspace session={session} onNavigate={navigate} routeSearch={search} />
      </div>

      {workspace === "matrix" && (
        <>
          <Header
            activeWorkspace="matrix"
            onNavigate={navigate}
            viewMode="forecastError"
            onViewMode={() => {}}
            palette="congestion"
            onPalette={() => {}}
            lastUpdated={lastUpdated}
            connectionState={connectionState}
          />
          <MatrixWorkspace
            timestamp={timestamps[currentIndex] ?? null}
            routeSearch={search}
            onSelectionRouteChange={(search) => navigate("matrix", search)}
            onNavigateToMap={(search) => navigate("map", search)}
          />
        </>
      )}

      <PlaybackScrubber
        timestamps={timestamps}
        currentIndex={currentIndex}
        onIndexChange={setCurrentIndex}
        loading={loading}
        sparkSeries={sparkSeries}
        eventLabel={
          CURATED_EVENTS.find((event) => event.id === activeEventId)?.label ?? null
        }
        leftSlot={
          <DateRangePicker
            onLoad={loadCustomWindow}
            onSelectEvent={selectEvent}
            events={CURATED_EVENTS}
            activeEventId={activeEventId}
            loading={loading}
          />
        }
      />
    </div>
  );
}
